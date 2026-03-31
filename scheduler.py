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

# Force UTF-8 output so Unicode banner renders correctly on Windows
if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
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
    triggered_synthesis: bool = False  # True if this child's completion queued parent synthesis


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
            try:
                print(f"       {msg}", flush=True)
            except OSError:
                print(f"       {msg.encode('ascii', errors='replace').decode()}", flush=True)

    try:
        # Mark active now (inside worker, not before pool starts)
        topics.update_status(note.slug, "active")

        model = roster.get_model_for(note) if roster else cfg.get("ollama.model")
        _p(f"model: {model}")

        existing_body = note.body or ""
        topic_context = get_research_prompt(note.type, note.name, existing_body,
                                            depth=note.research_depth)
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
                    fetch_failed = any(x in tool_result for x in (
                        "Failed to fetch", "Timed out", "HTTP error", "Invalid URL",
                        "timed out after", "Failed:", "Error:",
                    ))
                    if fetch_failed:
                        _p(f"  ! fetch failed: {tool_result[:80]}")
                        log.warn("source_fetch_failed", url=url, topic=note.slug)
                    else:
                        # Only record sources that actually returned content
                        memory.record_source(url, topic_slug=note.slug)
                        outcome.sources_found += 1
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

        # Consensus mode: only run at depth 2+ (deep research) to avoid wasting
        # time on shallow/first-pass topics. Depth 0-1 = gather phase, not worth a second model.
        consensus_min_depth = cfg.get("agent.consensus_min_depth", 2)
        if cfg.get("agent.consensus_mode", False) and note.research_depth >= consensus_min_depth:
            try:
                from consensus import run_consensus_research
                _p(f"→ consensus: depth {note.research_depth} — running multi-model review...")
                c_result = run_consensus_research(note, vault, memory, topics, roster)
                if c_result and c_result.merged_body:
                    c_note = vault.read_note(note.slug)
                    if c_note:
                        c_note.body = c_result.merged_body
                        vault.write_note(c_note)
                    if c_result.conflicts:
                        _p(f"  ⚡ {len(c_result.conflicts)} conflict(s) flagged between models")
            except Exception as e:
                _p(f"  ! consensus failed: {e}")
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
            new_depth = topics.increment_depth(note.slug)
            _p(f"depth → {new_depth}")
            log.note_written(note.slug, outcome.sources_found)
            log.topic_done(note, outcome.elapsed_s, outcome.sources_found,
                           outcome.memories_saved, outcome.iterations)
            outcome.success = True

            # Notify parent tree node that a child has finished
            if note.parent_slug:
                syn_result = topics.on_child_completed(note.parent_slug)
                _p(f"→ parent '{note.parent_slug}': {syn_result}")
                outcome.triggered_synthesis = (syn_result == "synthesizing")
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


# ── Synthesis worker ─────────────────────────────────────────────────────────

def _synthesis_worker(
    parent_note,
    vault: VaultManager,
    roster,
    db_path: str,
    print_lock: threading.Lock,
    log,
) -> ResearchOutcome:
    """
    Roll-up worker: reads all children, calls LLM to synthesise a master summary,
    writes the parent note, marks it 'complete'.
    """
    outcome = ResearchOutcome(slug=parent_note.slug, name=parent_note.name, success=False)
    memory = MemoryStore(db_path)
    topics = TopicManager(vault)
    t_start = time.time()

    def _p(msg: str):
        with print_lock:
            try:
                print(f"       {msg}", flush=True)
            except OSError:
                print(f"       {msg.encode('ascii', errors='replace').decode()}", flush=True)

    try:
        _p(f"synthesising {len(parent_note.children_slugs)} children for '{parent_note.name}'")

        # Load all child notes
        children = []
        for slug in parent_note.children_slugs:
            child = vault.read_note(slug)
            if child:
                children.append(child)
        if not children:
            outcome.error = "No child notes found — synthesis skipped"
            _p(f"! {outcome.error}")
            # Revert to waiting so it can be retried
            stuck = vault.read_note(parent_note.slug)
            if stuck:
                stuck.status = "waiting_on_children"
                vault.write_note(stuck)
            return outcome

        from planner import build_synthesis_prompt
        synthesis_prompt = build_synthesis_prompt(parent_note, children)

        model = roster.get_model_for(parent_note) if roster else cfg.get("ollama.model")
        _p(f"model: {model} | {len(children)} children loaded")

        from llm import chat
        messages = [{"role": "user", "content": synthesis_prompt}]
        from prompts import build_system_prompt, parse_tool_call
        from tools import TOOL_REGISTRY_SYNTHESIS_ONLY, format_tools_for_prompt

        # Build a synthesis-specific system prompt that only exposes read_local_vault
        synthesis_tools_text = "\n".join(
            f"### {t['name']}\n{t['description']}\nExample: `{t['example']}`"
            for t in TOOL_REGISTRY_SYNTHESIS_ONLY
        )
        system_prompt = (
            "You are a research synthesis assistant. You have already been provided with "
            "the sub-topic research below. Write a comprehensive, integrated master note "
            "for the parent topic. You may call read_local_vault to load additional vault notes "
            "if you need more detail.\n\n"
            f"## Available tool\n{synthesis_tools_text}\n\n"
            "Output the final note body as plain markdown starting with # TopicName."
        )

        max_iter = min(cfg.get("agent.max_iterations", 8), 4)
        final_body = ""

        for iteration in range(max_iter):
            _p(f"synthesis iteration {iteration + 1}/{max_iter}")
            response = chat(messages, system_prompt, stream=False, model=model)
            tool_call = parse_tool_call(response)

            if tool_call is None:
                # Model returned the synthesis — capture it
                final_body = response.strip()
                break

            if tool_call.get("tool") == "read_local_vault":
                _p(f"→ read_local_vault: {tool_call.get('slugs', '')}")
                tool_result = execute_tool(tool_call, memory, vault=vault, topics=topics)
                messages = messages + [
                    {"role": "assistant", "content": response},
                    {"role": "user", "content": f"[Vault content]\n{tool_result}\n\nNow write the synthesis."},
                ]
            else:
                # Unexpected tool — just continue
                messages = messages + [
                    {"role": "assistant", "content": response},
                    {"role": "user", "content": "Continue — write the synthesis now."},
                ]

        if not final_body:
            outcome.error = "Synthesis produced no output"
            _p(f"! {outcome.error}")
            return outcome

        # Write the updated parent note
        parent = vault.read_note(parent_note.slug)
        if parent:
            parent.body = final_body
            parent.status = "complete"
            parent.last_researched = str(date.today())
            parent.research_runs += 1
            parent.last_run_elapsed_s = round(time.time() - t_start, 1)
            vault.write_note(parent)
            outcome.words_written = len(final_body.split())
            outcome.success = True
            _p(f"✓ synthesis complete — {outcome.words_written} words")
            log.note_written(parent_note.slug, 0)

        memory.close()

    except Exception as e:
        import traceback as _tb
        outcome.error = str(e)
        outcome.elapsed_s = time.time() - t_start
        _p(f"! synthesis error: {e}")
        log.topic_failed(parent_note, str(e), _tb.format_exc())
        memory.close()

    outcome.elapsed_s = time.time() - t_start
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

        # ── Synthesis pass: pick up any parents that are ready to synthesise ──
        synthesis_candidates = self.topics.get_synthesis_candidates()
        if synthesis_candidates:
            print(f"\n  Synthesis pass: {len(synthesis_candidates)} parent(s) ready for roll-up", flush=True)
            syn_futures = {}
            with ThreadPoolExecutor(max_workers=1) as syn_pool:
                for syn_note in synthesis_candidates:
                    print(f"  [SYN] {syn_note.name}", flush=True)
                    f = syn_pool.submit(
                        _synthesis_worker, syn_note, self.vault, self.roster,
                        db_path, print_lock, self.log,
                    )
                    syn_futures[f] = syn_note
                for f in as_completed(syn_futures):
                    syn_note = syn_futures[f]
                    try:
                        syn_outcome = f.result()
                        result.outcomes.append(syn_outcome)
                        result.topics_attempted += 1
                        if syn_outcome.success:
                            result.topics_succeeded += 1
                        else:
                            result.topics_failed += 1
                    except Exception as e:
                        print(f"  [SYN] FAILED {syn_note.name}: {e}", flush=True)

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


# ── Loop Scheduler ────────────────────────────────────────────────────────────

class LoopScheduler:
    """
    Continuously picks topics via weighted random selection and researches them.
    Never exits — designed for always-on / overnight use.

    Config keys (all in schedule.*):
        loop_sleep_between_topics_s  — pause between topics (default: 30)
        loop_batch_size              — topics per batch before a longer rest (default: 3)
        loop_batch_rest_s            — rest between batches (default: 120)
        loop_max_runtime_hours       — safety ceiling, 0 = unlimited (default: 0)
    """

    def __init__(self, memory: MemoryStore, vault: VaultManager,
                 topics: TopicManager, roster=None):
        self.memory = memory
        self.vault = vault
        self.topics = topics

        if roster is None:
            from agents import AgentRoster
            roster = AgentRoster()
        self.roster = roster

        from logger import PhantomLogger
        self.log = PhantomLogger()

        self.sleep_between = cfg.get("schedule.loop_sleep_between_topics_s", 30)
        self.batch_size    = cfg.get("schedule.loop_batch_size", 3)
        self.batch_rest    = cfg.get("schedule.loop_batch_rest_s", 120)
        self.max_hours     = cfg.get("schedule.loop_max_runtime_hours", 0)

        self._stop_event = threading.Event()
        self._total_researched = 0
        self._force_queue: list = []   # topics pushed to front via force_research()

    def stop(self):
        """Signal the loop to exit cleanly after the current topic finishes."""
        self._stop_event.set()

    def force_research(self, note) -> None:
        """Push a specific topic to the front of the next pick."""
        self._force_queue.insert(0, note)

    def run(self) -> None:
        db_path = cfg.get("memory.db_path", "data/memory.db")
        print_lock = threading.Lock()
        loop_start = time.time()
        batch_count = 0
        model = cfg.get("ollama.model", "unknown")

        self.log.run_start("loop", model, 0)
        print(f"\nLoop mode active — Ctrl+C to stop", flush=True)
        print(f"  Batch size: {self.batch_size} topics | Sleep: {self.sleep_between}s between | {self.batch_rest}s between batches", flush=True)
        print("─" * 50, flush=True)

        while not self._stop_event.is_set():
            # Runtime ceiling check
            if self.max_hours > 0:
                elapsed_h = (time.time() - loop_start) / 3600
                if elapsed_h >= self.max_hours:
                    print(f"\nLoop runtime limit reached ({self.max_hours}h). Stopping.", flush=True)
                    break

            # Pick next topic
            pool_size = 0
            if self._force_queue:
                note = self._force_queue.pop(0)
                print(f"\n[FORCED] {note.name}", flush=True)
            else:
                candidates = self.topics.get_loop_candidates()
                if not candidates:
                    print("No topics available. Sleeping 60s...", flush=True)
                    self._stop_event.wait(60)
                    continue
                pool_size = len(candidates)
                note = self.topics.weighted_pick(candidates)

            if not note:
                self._stop_event.wait(self.sleep_between)
                continue

            position = self._total_researched + 1
            depth_label = f"depth {note.research_depth}"
            print(f"\n[#{position} of {pool_size}] {note.name}  ({note.type}/{note.priority}, {depth_label})", flush=True)
            self.log.topic_start(note, position, pool_size)

            try:
                outcome = _worker(
                    note, position, pool_size,
                    self.vault, self.roster, db_path, print_lock, self.log,
                )
            except Exception as e:
                print(f"       ── WORKER CRASH: {e} — continuing loop", flush=True)
                self.log.topic_failed(note, str(e))
                self._stop_event.wait(self.sleep_between)
                continue

            self._total_researched += 1
            batch_count += 1

            with print_lock:
                if outcome.success:
                    print(
                        f"       ── Done [{_fmt_duration(outcome.elapsed_s)}]"
                        f" — {outcome.sources_found} sources,"
                        f" {outcome.memories_saved} memories,"
                        f" {outcome.iterations} iterations",
                        flush=True,
                    )
                else:
                    print(f"       ── FAILED: {outcome.error}", flush=True)

            # Rebuild after each topic in loop mode
            try:
                self.vault.rebuild_backlinks()
                self.vault.rebuild_index()
            except Exception as e:
                print(f"       ── rebuild error (non-fatal): {e}", flush=True)

            if self._stop_event.is_set():
                break

            # Batch rest
            if batch_count >= self.batch_size:
                print(f"\n  Batch of {self.batch_size} complete — resting {self.batch_rest}s...", flush=True)
                batch_count = 0
                self._stop_event.wait(self.batch_rest)
            else:
                self._stop_event.wait(self.sleep_between)

        print(f"\nLoop stopped. Total topics researched: {self._total_researched}", flush=True)
        self.log.run_done(self._total_researched, 0, time.time() - loop_start)
        self.log.close()


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
