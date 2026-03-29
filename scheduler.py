"""
Scheduled research mode — python agent.py --schedule
Works through the research queue and stale topics using a thread pool,
writes to vault, then exits cleanly.
Designed to run under Windows Task Scheduler.
"""
import sys
import time
import threading
import traceback as _traceback
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import date

from config import cfg
from llm import check_connection, OllamaConnectionError
from memory import MemoryStore
from vault import VaultManager
from topics import TopicManager
from templates import get_research_prompt
from prompts import build_system_prompt, parse_tool_call
from tools import execute_tool


def _fmt_duration(seconds: float) -> str:
    s = int(seconds)
    if s >= 60:
        return f"{s // 60}m {s % 60}s"
    return f"{s}s"


@dataclass
class ResearchOutcome:
    slug: str
    name: str
    success: bool
    sources_found: int = 0
    words_written: int = 0
    memories_saved: int = 0
    iterations: int = 0
    had_conflicts: bool = False
    elapsed_s: float = 0.0
    error: str = ""


@dataclass
class SchedulerResult:
    topics_attempted: int = 0
    topics_succeeded: int = 0
    topics_failed: int = 0
    outcomes: list = field(default_factory=list)
    digest_path: str = ""


# ── Thread worker ─────────────────────────────────────────────────────────────

def _worker(
    note,
    position: int,
    total: int,
    vault: VaultManager,
    roster,
    db_path: str,
    print_lock: threading.Lock,
    log,
) -> ResearchOutcome:
    outcome = ResearchOutcome(slug=note.slug, name=note.name, success=False)
    memory = MemoryStore(db_path)
    topics = TopicManager(vault)
    t_start = time.time()
    memories_before = memory.total_facts()

    def _p(msg: str):
        with print_lock:
            print(f"       {msg}", flush=True)

    try:
        # Mark active now (inside worker, not before pool starts)
        topics.update_status(note.slug, "active")

        model = roster.get_model_for(note) if roster else cfg.get("ollama.model")
        _p(f"model: {model}")

        existing_body = note.body or ""
        topic_context = get_research_prompt(note.type, note.name, existing_body)
        system_prompt = build_system_prompt(topic_context=topic_context)

        # Inject any new RSS feed items as context
        feed_context = ""
        try:
            from rss import fetch_new_items, format_feed_context
            feed_items = fetch_new_items(note)
            if feed_items:
                feed_context = format_feed_context(feed_items)
                _p(f"→ feeds: {len(feed_items)} new item(s) from {len(note.feeds)} feed(s)")
        except Exception:
            pass

        feed_prefix = f"\n{feed_context}\n" if feed_context else ""
        task_message = (
            f"{feed_prefix}Please research '{note.name}' and update the vault note. "
            f"Start by calling read_note to check what is already known, "
            f"then use web_search and fetch_page to gather current information, "
            f"then call update_note with your complete findings."
        )
        memory.add_message("user", task_message)
        messages = memory.get_messages()

        max_iter = cfg.get("agent.max_iterations", 8)
        fetch_count = 0

        for iteration in range(max_iter):
            outcome.iterations = iteration + 1

            _p(f"thinking... (iteration {iteration + 1}/{max_iter})")

            from llm import chat
            t_tool = time.time()
            response = chat(messages, system_prompt, stream=False, model=model)
            tool_call = parse_tool_call(response)

            if tool_call is None:
                _p("research complete — writing final answer")
                break

            tool_name = tool_call.get("tool", "")
            elapsed_ms = int((time.time() - t_tool) * 1000)

            # Print human-readable tool call line
            if tool_name == "web_search":
                _p(f"→ web_search: \"{tool_call.get('query', '')}\"")
            elif tool_name == "fetch_page":
                fetch_count += 1
                _p(f"→ fetch_page: {tool_call.get('url', '')[:80]}")
            elif tool_name == "update_note":
                _p(f"→ update_note: writing vault note...")
            elif tool_name == "read_note":
                _p(f"→ read_note: {tool_call.get('topic', '')}")
            elif tool_name == "remember":
                _p(f"→ remember: {tool_call.get('content', '')[:60]}...")
            else:
                _p(f"→ {tool_name}")

            log.tool_call(tool_name, topic_slug=note.slug, **{
                k: v for k, v in tool_call.items() if k != "tool"
            })

            tool_result = execute_tool(tool_call, memory, vault=vault, topics=topics)

            if tool_name == "fetch_page":
                url = tool_call.get("url", "")
                if url:
                    memory.record_source(url, topic_slug=note.slug)
                    outcome.sources_found += 1
                    if any(x in tool_result for x in ("Failed", "Timed out", "HTTP error")):
                        _p(f"  ! fetch failed: {tool_result[:80]}")
                        log.warn("source_fetch_failed", url=url, topic=note.slug)
                    else:
                        _p(f"  ✓ fetched {len(tool_result)} chars")
                        log.tool_result(tool_name, elapsed_ms, topic_slug=note.slug, url=url)
                else:
                    log.tool_result(tool_name, elapsed_ms, topic_slug=note.slug)
            elif tool_name == "web_search":
                import re as _re
                result_count = len(_re.findall(r"^\d+\.", tool_result, _re.MULTILINE))
                _p(f"  ✓ {result_count} result(s) found")
                log.tool_result(tool_name, elapsed_ms, topic_slug=note.slug,
                                results_count=result_count)
            elif tool_name == "remember":
                import re as _re
                m = _re.search(r"id=(\d+)", tool_result)
                if m:
                    log.memory_saved(int(m.group(1)), note.slug)
                log.tool_result(tool_name, elapsed_ms, topic_slug=note.slug)
            else:
                log.tool_result(tool_name, elapsed_ms, topic_slug=note.slug)

            messages = messages + [
                {"role": "assistant", "content": response},
                {"role": "user", "content": f"[Tool result for {tool_name}]\n{tool_result}\n\nContinue."},
            ]

        memory.clear_session()

        # Consensus mode: run again with a second model and merge
        consensus_models = cfg.get("schedule.consensus_models", [])
        if consensus_models and len(consensus_models) >= 2:
            try:
                from consensus import run_consensus_research
                _p(f"→ consensus: running second model {consensus_models[1]}...")
                c_result = run_consensus_research(note, vault, memory, topics, roster)
                if c_result and c_result.merged_body:
                    c_note = vault.read_note(note.slug)
                    if c_note:
                        c_note.body = c_result.merged_body
                        vault.write_note(c_note)
                    if c_result.conflicts:
                        _p(f"  ⚡ {len(c_result.conflicts)} conflict(s) flagged between models")
            except Exception:
                pass  # consensus is optional — never fail the whole run

        updated_note = vault.read_note(note.slug)
        if updated_note:
            outcome.words_written = len(updated_note.body.split())
            outcome.had_conflicts = "> [!warning]" in (updated_note.body or "")
            outcome.memories_saved = memory.total_facts() - memories_before
            outcome.elapsed_s = time.time() - t_start

            # Update frontmatter stats
            updated_note.research_runs += 1
            updated_note.total_sources_fetched += outcome.sources_found
            updated_note.total_memories_saved += outcome.memories_saved
            updated_note.last_run_elapsed_s = round(outcome.elapsed_s, 1)
            updated_note.last_run_iterations = outcome.iterations
            vault.write_note(updated_note)

            topics.mark_researched(note.slug)
            log.note_written(note.slug, outcome.sources_found)
            log.topic_done(note, outcome.elapsed_s, outcome.sources_found,
                           outcome.memories_saved, outcome.iterations)
            outcome.success = True
        else:
            outcome.error = "Note not found after research (update_note may not have been called)"
            log.topic_failed(note, outcome.error)

    except OllamaConnectionError as e:
        outcome.error = f"Ollama connection lost: {e}"
        outcome.elapsed_s = time.time() - t_start
        log.topic_failed(note, outcome.error, _traceback.format_exc())
    except Exception as e:
        outcome.error = str(e)
        outcome.elapsed_s = time.time() - t_start
        log.topic_failed(note, outcome.error, _traceback.format_exc())
    finally:
        memory.close()

    return outcome


# ── Scheduler ─────────────────────────────────────────────────────────────────

class ResearchScheduler:
    def __init__(
        self,
        memory: MemoryStore,
        vault: VaultManager,
        topics: TopicManager,
        roster=None,
        max_topics: int = None,
    ):
        self.memory = memory
        self.vault = vault
        self.topics = topics
        self.max_topics = max_topics or cfg.get("schedule.max_topics_per_run", 10)
        self.max_workers = cfg.get("schedule.max_parallel_workers", 2)

        if roster is None:
            from agents import AgentRoster
            roster = AgentRoster()
        self.roster = roster

        from logger import PhantomLogger
        self.log = PhantomLogger()

    def run(self) -> SchedulerResult:
        result = SchedulerResult()

        candidates = self.topics.get_research_candidates()
        if not candidates:
            print("Nothing to research. Queue is empty and no stale topics.", flush=True)
            return result

        candidates = candidates[: self.max_topics]
        total = len(candidates)
        db_path = cfg.get("memory.db_path", "data/memory.db")
        print_lock = threading.Lock()
        model = cfg.get("ollama.model", "unknown")

        print(f"\nScheduled run: {total} topic(s) | {self.max_workers} worker(s)", flush=True)
        print("─" * 50, flush=True)

        self.log.run_start("scheduled", model, total)

        run_start = time.time()
        completed_times: list[float] = []

        futures = {}
        with ThreadPoolExecutor(max_workers=self.max_workers) as pool:
            for i, note in enumerate(candidates, 1):
                # Print topic banner IMMEDIATELY when submitting — not after completing
                print(f"\n[{i}/{total}] {note.name}  ({note.type}/{note.priority})", flush=True)
                self.log.topic_start(note, i, total)
                future = pool.submit(
                    _worker, note, i, total, self.vault, self.roster,
                    db_path, print_lock, self.log,
                )
                futures[future] = (note, i)

            for future in as_completed(futures):
                note, position = futures[future]
                try:
                    outcome = future.result()
                except Exception as e:
                    outcome = ResearchOutcome(slug=note.slug, name=note.name,
                                             success=False, error=str(e))

                result.outcomes.append(outcome)
                result.topics_attempted += 1
                completed_times.append(outcome.elapsed_s)

                with print_lock:
                    if outcome.success:
                        result.topics_succeeded += 1
                        conflict_tag = "  [!] conflicts flagged" if outcome.had_conflicts else ""
                        print(
                            f"       ── Done [{_fmt_duration(outcome.elapsed_s)}]"
                            f" — {outcome.sources_found} sources,"
                            f" {outcome.memories_saved} memories,"
                            f" {outcome.iterations} iterations"
                            f"{conflict_tag}",
                            flush=True,
                        )
                        remaining = total - len(completed_times)
                        if remaining > 0 and len(completed_times) >= 1:
                            avg = sum(completed_times) / len(completed_times)
                            eta_s = avg * remaining
                            print(f"       ETA: ~{remaining} remaining,"
                                  f" ~{_fmt_duration(eta_s)} estimated", flush=True)
                    else:
                        result.topics_failed += 1
                        print(f"       ── FAILED: {outcome.error}", flush=True)

        print(f"\nRebuilding backlinks...", flush=True)
        self.vault.rebuild_backlinks()
        self.vault.rebuild_index()

        total_elapsed = time.time() - run_start

        if cfg.get("schedule.generate_daily_digest", True) and result.topics_succeeded > 0:
            result.digest_path = self._generate_daily_digest(result.outcomes)

        self.log.run_done(result.topics_succeeded, result.topics_failed, total_elapsed)
        self.log.close()

        failed_names = [o.name for o in result.outcomes if not o.success]
        avg_s = total_elapsed / result.topics_succeeded if result.topics_succeeded else 0

        print(f"\n{'─' * 50}", flush=True)
        print(
            f"Run complete: {result.topics_succeeded}/{result.topics_attempted} succeeded"
            f"  |  {result.topics_failed} failed"
            f"  |  {_fmt_duration(total_elapsed)} total",
            flush=True,
        )
        if result.topics_succeeded:
            print(f"Avg per topic: {_fmt_duration(avg_s)}"
                  f"  |  Vault notes written: {result.topics_succeeded}", flush=True)
        if failed_names:
            log_path = f"logs/phantom-{date.today()}.log"
            print(f"Failed: {', '.join(failed_names)}  (see {log_path})", flush=True)
        if result.digest_path:
            print(f"Daily digest: {result.digest_path}", flush=True)
        print("─" * 50, flush=True)

        return result

    def _generate_daily_digest(self, outcomes: list[ResearchOutcome]) -> str:
        today = str(date.today())
        digest_dir = f"{cfg.get('vault.path', 'vault')}/daily"
        digest_path = f"{digest_dir}/{today}.md"

        succeeded = [o for o in outcomes if o.success]
        failed = [o for o in outcomes if not o.success]
        conflict_count = sum(1 for o in succeeded if o.had_conflicts)

        lines = [
            "---",
            f"date: {today}",
            "type: daily-digest",
            f"topics_researched: {len(succeeded)}",
            f"topics_failed: {len(failed)}",
            "---",
            "",
            f"# Research Digest — {today}",
            "",
            "## Summary",
            "",
            f"Researched {len(succeeded)} topic(s) in this scheduled run.",
        ]

        if conflict_count:
            lines.append(f"{conflict_count} topic(s) had conflicting information flagged — review those notes.")
        if failed:
            lines.append(f"{len(failed)} topic(s) failed to research.")

        lines += [""]

        if succeeded:
            lines += ["## Topics Researched", ""]
            for o in succeeded:
                lines.append(f"### [[{o.name}]]")
                lines.append(f"- Words written: {o.words_written}")
                lines.append(f"- Sources found: {o.sources_found}")
                lines.append(f"- Memories saved: {o.memories_saved}")
                lines.append(f"- Time: {_fmt_duration(o.elapsed_s)}")
                if o.had_conflicts:
                    lines.append("- **Conflicts flagged** — see note for `[!warning]` callouts")
                lines.append("")

        if failed:
            lines += ["## Failed Topics", ""]
            for o in failed:
                lines.append(f"- **{o.name}**: {o.error}")
            lines.append("")

        new_links = []
        for o in succeeded:
            note = self.vault.read_note(o.slug)
            if note and note.forward_links:
                new_links.append((note.name, note.forward_links))

        if new_links:
            lines += ["## Links Discovered", ""]
            for name, links in new_links:
                fwd = ", ".join(f"[[{l}]]" for l in links)
                lines.append(f"- [[{name}]] links to: {fwd}")
            lines.append("")

        import os
        os.makedirs(digest_dir, exist_ok=True)
        with open(digest_path, "w", encoding="utf-8") as f:
            f.write("\n".join(lines))

        return digest_path


_BANNER = """
  ██████╗ ██╗  ██╗ █████╗ ███╗   ██╗████████╗ ██████╗ ███╗   ███╗
  ██╔══██╗██║  ██║██╔══██╗████╗  ██║╚══██╔══╝██╔═══██╗████╗ ████║
  ██████╔╝███████║███████║██╔██╗ ██║   ██║   ██║   ██║██╔████╔██║
  ██╔═══╝ ██╔══██║██╔══██║██║╚██╗██║   ██║   ██║   ██║██║╚██╔╝██║
  ██║     ██║  ██║██║  ██║██║ ╚████║   ██║   ╚██████╔╝██║ ╚═╝ ██║
  ╚═╝     ╚═╝  ╚═╝╚═╝  ╚═╝╚═╝  ╚═══╝   ╚═╝    ╚═════╝ ╚═╝     ╚═╝
                    off-network-agent
"""


# ── Entry point ───────────────────────────────────────────────────────────────

def run_scheduled():
    print(_BANNER, flush=True)
    print("=" * 68, flush=True)
    print("  Phantom — Scheduled Research Mode", flush=True)
    print("=" * 68, flush=True)

    ok, msg = check_connection()
    if not ok:
        print(f"\nAborting: {msg}", flush=True)
        sys.exit(1)
    print(f"  {msg}", flush=True)

    from context import load_context
    load_context()

    db_path = cfg.get("memory.db_path", "data/memory.db")
    memory = MemoryStore(db_path)

    vault_path = cfg.get("vault.path", "vault")
    vault = VaultManager(vault_path)
    topics = TopicManager(vault)

    from agents import AgentRoster
    roster = AgentRoster()

    queued = len(topics.list_topics(status="queued"))
    stale = len(topics.get_stale_topics())
    workers = cfg.get("schedule.max_parallel_workers", 2)
    print(f"  Queue: {queued} queued | {stale} stale active | {workers} parallel worker(s)",
          flush=True)
    print("=" * 56, flush=True)

    scheduler = ResearchScheduler(memory, vault, topics, roster=roster)
    result = scheduler.run()

    memory.close()
    sys.exit(0 if result.topics_failed == 0 else 1)
