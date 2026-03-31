"""
planner.py — Nested Research Tree decomposition

Given a "Big Topic" note, call the LLM to decompose it into 3-5 focused
sub-topic names, then create child notes and update the parent's tree fields.

Entry point: decompose_topic(note, vault, topics, roster)
"""

import json
import re
import logging
from datetime import date

from vault import VaultManager, Note
from topics import TopicManager

logger = logging.getLogger(__name__)

# ── Decomposition prompt ──────────────────────────────────────────────────────

_DECOMPOSE_PROMPT = """\
You are a research planning assistant. Your job is to break a broad research topic into 3 to 5 focused sub-topics that together cover the topic comprehensively.

Topic to decompose: "{topic_name}"
Topic type: {topic_type}
Tags: {tags}

Rules:
- Return ONLY a JSON array of sub-topic name strings — nothing else.
- Each sub-topic must be a specific, researchable question or concept (not just a single word).
- Sub-topics must be distinct and non-overlapping.
- Aim for depth over breadth: each sub-topic should be narrow enough to research in one session.
- Do not number them or add explanations.

Example output for topic "Machine Learning":
["Supervised vs Unsupervised Learning", "Neural Network Architectures", "Gradient Descent Optimisation", "Overfitting and Regularisation", "ML Model Evaluation Metrics"]

Now decompose: "{topic_name}"
"""

# ── LLM call (thin wrapper matching existing pattern) ─────────────────────────

def _call_llm(prompt: str, roster) -> str:
    """Call the LLM via the roster's primary model. Returns raw text."""
    try:
        model = roster.primary_model() if roster else None
        if model is None:
            from config import cfg
            import requests as _req
            base_url = cfg.get("ollama.base_url", "http://localhost:11434")
            model_name = cfg.get("ollama.model", "llama3.1:8b")
            timeout = cfg.get("ollama.timeout", 60)
            resp = _req.post(
                f"{base_url}/api/generate",
                json={"model": model_name, "prompt": prompt, "stream": False},
                timeout=timeout,
            )
            resp.raise_for_status()
            return resp.json().get("response", "")
        return model.generate(prompt)
    except Exception as e:
        logger.warning(f"planner LLM call failed: {e}")
        return ""


def _parse_subtopics(raw: str) -> list[str]:
    """Extract a JSON array of strings from LLM output."""
    raw = raw.strip()
    # Try to find JSON array
    match = re.search(r"\[.*?\]", raw, re.DOTALL)
    if match:
        try:
            items = json.loads(match.group())
            if isinstance(items, list):
                return [str(i).strip() for i in items if str(i).strip()]
        except json.JSONDecodeError:
            pass
    # Fallback: parse numbered or bulleted list
    items = []
    for line in raw.splitlines():
        line = re.sub(r"^[\d\.\-\*\s]+", "", line).strip().strip('"').strip("'")
        if len(line) > 3:
            items.append(line)
    return items[:5]  # cap at 5 even in fallback


# ── Main entry point ──────────────────────────────────────────────────────────

def decompose_topic(
    note: Note,
    vault: VaultManager,
    topics: TopicManager,
    roster=None,
    max_children: int = 5,
    min_children: int = 2,
) -> list[Note]:
    """
    Decompose a Big Topic into child sub-topics.

    1. Calls the LLM with a scoping prompt.
    2. For each child name: checks for slug collision (cross-pollination) or creates new child.
    3. Updates the parent note's tree fields (children_slugs, child_count, status).
    4. Returns list of child Note objects created/reused.

    Does nothing and returns [] if the note already has children or is not in a plannable state.
    """
    if note.child_count > 0:
        logger.info(f"planner: {note.slug} already has {note.child_count} children, skipping")
        return []

    if note.status not in ("queued", "active"):
        logger.info(f"planner: {note.slug} status={note.status}, cannot plan")
        return []

    # Mark parent as planning (transient)
    note.status = "planning"
    vault.write_note(note)
    logger.info(f"planner: decomposing '{note.name}' …")

    try:
        prompt = _DECOMPOSE_PROMPT.format(
            topic_name=note.name,
            topic_type=note.type,
            tags=", ".join(note.tags) if note.tags else "none",
        )
        raw = _call_llm(prompt, roster)
        child_names = _parse_subtopics(raw)
        child_names = child_names[:max_children]

        if len(child_names) < min_children:
            logger.warning(f"planner: only {len(child_names)} sub-topics for '{note.name}', reverting to queued")
            note.status = "queued"
            vault.write_note(note)
            return []

        children: list[Note] = []
        children_slugs: list[str] = []

        for child_name in child_names:
            child = topics.create_child_topic(
                parent_slug=note.slug,
                child_name=child_name,
                type=note.type,
                priority=note.priority,
                tags=list(note.tags),
            )
            children.append(child)
            children_slugs.append(child.slug)
            logger.info(f"  child: {child.slug} (depth={child.tree_depth})")

        # Update parent with tree metadata
        parent = vault.read_note(note.slug)
        if parent:
            parent.status = "waiting_on_children"
            parent.child_count = len(children)
            parent.children_done = 0
            parent.children_slugs = children_slugs
            vault.write_note(parent)

        vault.rebuild_index()
        logger.info(f"planner: created {len(children)} children for '{note.name}'")
        return children

    except Exception as e:
        logger.error(f"planner: decompose_topic failed for '{note.name}': {e}")
        # Revert to queued so the topic isn't stranded in 'planning'
        try:
            stuck = vault.read_note(note.slug)
            if stuck and stuck.status == "planning":
                stuck.status = "queued"
                vault.write_note(stuck)
        except Exception:
            pass
        return []


# ── Synthesis prompt builder ──────────────────────────────────────────────────

def build_synthesis_prompt(parent: Note, children: list[Note]) -> str:
    """
    Build the user-turn prompt for the synthesis worker.
    Injects child note bodies (capped) so the LLM can write a master summary.
    """
    child_sections = []
    for child in children:
        body_preview = child.body[:2000] if child.body else "*No content*"
        child_sections.append(
            f"### Sub-topic: {child.name}\n\n{body_preview}"
        )

    children_text = "\n\n---\n\n".join(child_sections)

    return f"""\
You are synthesising research on the topic: **{parent.name}**

The following {len(children)} sub-topics have been researched. Your task is to write a comprehensive master summary that:
1. Integrates findings from all sub-topics
2. Identifies cross-cutting themes and connections
3. Notes any contradictions or open questions
4. Includes [[WikiLinks]] to each sub-topic by name

## Sub-topic Research

{children_text}

---

Write the full updated note body for "{parent.name}" starting with # {parent.name}.
Include [[WikiLink]] references to each sub-topic. Be comprehensive but avoid simple concatenation.
"""
