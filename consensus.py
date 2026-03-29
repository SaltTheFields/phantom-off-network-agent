"""
Consensus mode — run the same research topic against two Ollama models,
then diff their findings and flag divergences.

Invoked automatically by scheduler when a topic has consensus_models set
in its frontmatter, or globally via config.json:
  "schedule": { "consensus_models": ["llama3.2", "mistral"] }

Can also be triggered manually:
  /research <topic> --consensus

How it works:
  1. Run topic through model_a → draft_a
  2. Run topic through model_b → draft_b
  3. Run a lightweight reconciler (model_a or broker) to:
     - Identify claims that agree (high confidence)
     - Identify claims that conflict (flagged with [!warning])
     - Merge into a single authoritative note
"""

import re
from dataclasses import dataclass, field


@dataclass
class ConsensusResult:
    agreed: list[str] = field(default_factory=list)       # claims both models agree on
    conflicts: list[tuple[str, str]] = field(default_factory=list)  # (claim_a, claim_b) pairs
    merged_body: str = ""
    model_a: str = ""
    model_b: str = ""


def _extract_bullet_claims(body: str) -> list[str]:
    """Pull bullet-point sentences from a markdown note body."""
    return [
        m.strip()
        for m in re.findall(r"^[-*]\s+(.+)$", body, re.MULTILINE)
        if len(m.strip()) > 20
    ]


def _sentences(body: str) -> list[str]:
    """Split body into sentences for broader claim extraction."""
    raw = re.sub(r"#+[^\n]*\n", "", body)   # strip headings
    raw = re.sub(r"\[.*?\]\(.*?\)", "", raw)  # strip links
    parts = re.split(r"(?<=[.!?])\s+", raw)
    return [p.strip() for p in parts if len(p.strip()) > 30]


def find_conflicts(body_a: str, body_b: str) -> list[tuple[str, str]]:
    """
    Simple heuristic conflict detector.
    Returns list of (sentence_from_a, sentence_from_b) that appear contradictory.
    """
    negation_words = [
        "not", "no longer", "never", "false", "incorrect", "wrong",
        "was previously", "used to", "deprecated", "removed", "discontinued",
        "however", "contrary", "contradicts", "disputes",
    ]

    sents_a = _sentences(body_a)
    sents_b = _sentences(body_b)
    conflicts = []

    for sa in sents_a:
        sa_lower = sa.lower()
        first_word = sa_lower.split()[0] if sa_lower.split() else ""
        if not first_word or len(first_word) < 4:
            continue
        for sb in sents_b:
            sb_lower = sb.lower()
            if first_word not in sb_lower:
                continue
            # One sentence negates the other
            a_has_neg = any(n in sa_lower for n in negation_words)
            b_has_neg = any(n in sb_lower for n in negation_words)
            if a_has_neg != b_has_neg:
                pair = (sa.strip(), sb.strip())
                if pair not in conflicts:
                    conflicts.append(pair)

    return conflicts[:10]  # cap to avoid overwhelming the note


def merge_with_llm(
    topic_name: str,
    body_a: str,
    body_b: str,
    model_a: str,
    model_b: str,
    reconciler_model: str = None,
) -> ConsensusResult:
    """
    Use the LLM to merge two research drafts into one authoritative note.
    Conflicts get [!warning] callouts in the merged body.
    """
    from llm import chat
    from config import cfg

    reconciler = reconciler_model or cfg.get("ollama.broker_model") or cfg.get("ollama.model")
    conflicts = find_conflicts(body_a, body_b)

    system = (
        "You are a research editor. You have received two research drafts on the same topic "
        "from different AI models. Your job is to merge them into a single, authoritative markdown note. "
        "Rules:\n"
        "- Where both drafts agree, state the claim confidently.\n"
        "- Where they conflict, include BOTH claims and mark them with a > [!warning] Conflict callout.\n"
        "- Keep all citations and source URLs from both drafts.\n"
        "- Use the format: # Topic Name\\n\\n## Section...\\n- bullet points\\n\n"
        "- Be concise. Do not repeat yourself.\n"
        "- Output ONLY the merged markdown note. No preamble."
    )

    conflict_block = ""
    if conflicts:
        lines = ["\n## Known Conflicts Between Models\n"]
        for ca, cb in conflicts:
            lines.append(f"- Model A ({model_a}): {ca}")
            lines.append(f"  Model B ({model_b}): {cb}")
        conflict_block = "\n".join(lines)

    user_msg = (
        f"# Topic: {topic_name}\n\n"
        f"## Draft from {model_a}:\n{body_a}\n\n"
        f"## Draft from {model_b}:\n{body_b}\n"
        f"{conflict_block}\n\n"
        "Please merge these into a single authoritative note with [!warning] callouts for conflicts."
    )

    try:
        merged = chat([{"role": "user", "content": user_msg}], system, stream=False, model=reconciler)
    except Exception as e:
        # Fallback: concatenate with conflict callouts embedded
        merged = _fallback_merge(topic_name, body_a, body_b, model_a, model_b, conflicts)

    result = ConsensusResult(
        model_a=model_a,
        model_b=model_b,
        conflicts=conflicts,
        merged_body=merged,
    )
    return result


def _fallback_merge(
    topic_name: str,
    body_a: str,
    body_b: str,
    model_a: str,
    model_b: str,
    conflicts: list[tuple[str, str]],
) -> str:
    """No-LLM fallback: concatenate both drafts with conflict warnings."""
    lines = [f"# {topic_name}", ""]
    if conflicts:
        lines += [
            "> [!warning] Consensus — Conflicts Detected",
            f"> Two models ({model_a}, {model_b}) produced conflicting findings.",
            "> Review flagged sections below.",
            "",
        ]
        for ca, cb in conflicts:
            lines += [
                "> [!warning] Conflict",
                f"> **{model_a}**: {ca}",
                f"> **{model_b}**: {cb}",
                "",
            ]

    lines += [
        f"## Research from {model_a}",
        "",
        body_a.strip(),
        "",
        f"## Research from {model_b}",
        "",
        body_b.strip(),
    ]
    return "\n".join(lines)


def run_consensus_research(note, vault, memory_a, topics, roster) -> ConsensusResult | None:
    """
    Run a topic through two models and return a ConsensusResult.
    Returns None if only one model is available.

    The two models are chosen from:
      1. Note's own 'consensus_models' frontmatter field
      2. config.json schedule.consensus_models (list of 2)
      3. roster — pick the two models assigned to this topic type
      4. Fallback: pick the first two available models
    """
    from config import cfg
    from llm import chat
    from prompts import build_system_prompt, parse_tool_call
    from templates import get_research_prompt
    from tools import execute_tool
    from memory import MemoryStore

    # 1. Topic-specific override
    consensus_models = getattr(note, "consensus_models", [])
    
    # 2. Global config fallback
    if not consensus_models or len(consensus_models) < 2:
        consensus_models = cfg.get("schedule.consensus_models", [])
    
    # 3. Roster / available fallback
    if not consensus_models or len(consensus_models) < 2:
        available = roster.list_available() if roster else []
        online = [a["model"] for a in available if a["available"]]
        if len(online) < 2:
            return None
        consensus_models = online[:2]

    model_a, model_b = consensus_models[0], consensus_models[1]
    if model_a == model_b:
        return None

    db_path = cfg.get("memory.db_path", "data/memory.db")

    def _run_single(model: str) -> str:
        """Run one full research loop for the topic, return final note body."""
        mem = MemoryStore(db_path)
        existing_body = note.body or ""
        topic_context = get_research_prompt(note.type, note.name, existing_body)
        system_prompt = build_system_prompt(topic_context=topic_context)
        task_msg = (
            f"Please research '{note.name}' thoroughly. "
            f"Use web_search and fetch_page to find current information. "
            f"Then provide a complete markdown research note starting with # {note.name}."
        )
        messages = [{"role": "user", "content": task_msg}]
        max_iter = cfg.get("agent.max_iterations", 8)
        final_body = ""

        for _ in range(max_iter):
            response = chat(messages, system_prompt, stream=False, model=model)
            tool_call = parse_tool_call(response)
            if tool_call is None:
                final_body = response
                break
            tool_result = execute_tool(tool_call, mem, vault=vault, topics=topics)
            messages = messages + [
                {"role": "assistant", "content": response},
                {"role": "user", "content": f"[Tool result]\n{tool_result}\n\nContinue."},
            ]
        mem.close()
        return final_body

    try:
        body_a = _run_single(model_a)
        body_b = _run_single(model_b)
        return merge_with_llm(note.name, body_a, body_b, model_a, model_b)
    except Exception:
        return None
