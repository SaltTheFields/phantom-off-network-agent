"""
OffNetWorkAgent — Local Ollama research agent with persistent memory.
Run: python agent.py
Run scheduled: python agent.py --schedule
"""
import sys
import os

# Force UTF-8 output so Unicode banner renders correctly on Windows
if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# Auditory feedback
def beep():
    if os.name == 'nt':
        import winsound
        winsound.Beep(1000, 300)
    else:
        print("\a", end="", flush=True)


from config import cfg
from llm import chat, check_connection, list_models, OllamaConnectionError
from memory import MemoryStore
from tools import execute_tool
from prompts import build_system_prompt, parse_tool_call
from vault import VaultManager
from topics import TopicManager
from context import load_context, get_context, reload_context
from agents import AgentRoster, CuratorAgent


# ── ReAct loop ────────────────────────────────────────────────────────────────

def run_agent_turn(
    user_message: str,
    memory: MemoryStore,
    vault: VaultManager = None,
    topics: TopicManager = None,
    roster: AgentRoster = None,
    silent: bool = False,
    forced_model: str = None,
) -> str:
    max_iter = cfg.get("agent.max_iterations", 8)
    verbose = cfg.get("agent.verbose", False) and not silent

    # 1. Select the right model for the job
    model = forced_model
    if not model and roster:
        curator = CuratorAgent(roster)
        model = curator.recommend_agent(user_message)
        if verbose:
            print(f"[curator] Selected model: {model}", flush=True)

    if not model:
        model = cfg.get("ollama.model")

    memory.add_message("user", user_message)
    memory.trim_history()

    mem_context = memory.build_memory_context(user_message)
    
    # 2. Check for specialized system prompt for this model
    custom_system_prompt = roster.get_system_prompt_for(model) if roster else ""
    system_prompt = build_system_prompt(memory_context=mem_context)
    if custom_system_prompt:
        system_prompt = f"## Personal Persona\n{custom_system_prompt}\n\n" + system_prompt

    messages = memory.get_messages()
    final_response = ""

    for iteration in range(max_iter):
        if verbose:
            print(f"\n[iter {iteration + 1}/{max_iter} | model: {model}]", flush=True)

        try:
            response = chat(messages, system_prompt, stream=not silent, model=model)
        except OllamaConnectionError as e:
            return f"Connection error: {e}"

        tool_call = parse_tool_call(response)

        if tool_call is None:
            final_response = response
            break

        tool_name = tool_call.get("tool", "unknown")
        if not silent:
            if verbose:
                print(f"\n[tool: {tool_name}] {tool_call}", flush=True)
            else:
                print(f"\n[using tool: {tool_name}...]", flush=True)

        tool_result = execute_tool(tool_call, memory, vault=vault, topics=topics)

        if verbose and not silent:
            print(f"[result]: {tool_result[:300]}{'...' if len(tool_result) > 300 else ''}", flush=True)

        messages = messages + [
            {"role": "assistant", "content": response},
            {"role": "user", "content": f"[Tool result for {tool_name}]\n{tool_result}\n\nContinue based on this result."},
        ]
    else:
        final_response = response

    memory.add_message("assistant", final_response)
    return final_response


# ── Topic CLI commands ────────────────────────────────────────────────────────

def handle_topic_command(arg: str, vault: VaultManager, topics: TopicManager) -> str:
    parts = arg.strip().split(maxsplit=1)
    sub = parts[0].lower() if parts else ""
    rest = parts[1] if len(parts) > 1 else ""

    if sub == "new":
        return _cmd_topic_new(rest, vault, topics)
    elif sub == "list":
        return _cmd_topic_list(rest, topics)
    elif sub == "show":
        return _cmd_topic_show(rest, topics)
    elif sub == "archive":
        return _cmd_topic_archive(rest, topics)
    elif sub == "queue":
        return _cmd_topic_queue(rest, topics)
    elif sub == "delete":
        return _cmd_topic_delete(rest, vault, topics)
    elif sub == "import":
        return _cmd_topic_import(rest, topics)
    elif sub == "export":
        return _cmd_topic_export(rest, topics)
    else:
        return (
            "Usage: /topic <subcommand>\n"
            "  new [name]          Create a new research topic\n"
            "  list [status]       List topics (all / queued / active / archived)\n"
            "  show <name>         Show topic details\n"
            "  queue <name>        Move topic to research queue\n"
            "  archive <name>      Archive a topic\n"
            "  delete <name>       Permanently delete a topic\n"
            "  import <file>       Bulk import from .txt or .json file\n"
            "  export [status]     Export topics to JSON file\n"
        )


def _cmd_topic_new(name: str, vault: VaultManager, topics: TopicManager) -> str:
    if not name:
        name = input("Topic name: ").strip()
    if not name:
        return "Cancelled."

    print(f"Type [{'/'.join(['research', 'person', 'tech', 'event', 'concept'])}] (default: research): ", end="")
    topic_type = input().strip() or "research"

    print("Priority [high/medium/low] (default: medium): ", end="")
    priority = input().strip() or "medium"

    print("Tags (comma-separated, optional): ", end="")
    tags_raw = input().strip()
    tags = [t.strip() for t in tags_raw.split(",") if t.strip()] if tags_raw else []

    print(f"Refresh interval in days (default: {cfg.get('vault.default_refresh_interval_days', 7)}): ", end="")
    interval_raw = input().strip()
    interval = int(interval_raw) if interval_raw.isdigit() else cfg.get("vault.default_refresh_interval_days", 7)

    try:
        note = topics.create_topic(
            name=name,
            type=topic_type,
            priority=priority,
            tags=tags,
            refresh_interval_days=interval,
        )
        return f"Created topic: {note.name} (slug: {note.slug}, type: {note.type}, priority: {note.priority})"
    except ValueError as e:
        return str(e)


def _cmd_topic_list(status_filter: str, topics: TopicManager) -> str:
    status = status_filter.strip() or None
    all_notes = topics.list_topics(status=status)
    return topics.format_topic_list(all_notes)


def _cmd_topic_show(name: str, topics: TopicManager) -> str:
    if not name:
        return "Usage: /topic show <name>"
    note = topics.get_topic(name)
    if not note:
        return f"Topic not found: '{name}'"
    return topics.format_topic_card(note)


def _cmd_topic_archive(name: str, topics: TopicManager) -> str:
    if not name:
        return "Usage: /topic archive <name>"
    note = topics.get_topic(name)
    if not note:
        return f"Topic not found: '{name}'"
    topics.archive_topic(note.slug)
    return f"Archived: {note.name}"


def _cmd_topic_queue(name: str, topics: TopicManager) -> str:
    if not name:
        return "Usage: /topic queue <name>"
    note = topics.get_topic(name)
    if not note:
        return f"Topic not found: '{name}'"
    topics.update_status(note.slug, "queued")
    return f"Queued: {note.name}"


def _cmd_topic_delete(name: str, vault: VaultManager, topics: TopicManager) -> str:
    if not name:
        return "Usage: /topic delete <name>"
    note = topics.get_topic(name)
    if not note:
        return f"Topic not found: '{name}'"
    confirm = input(f"Delete '{note.name}' permanently? (y/N): ").strip().lower()
    if confirm != "y":
        return "Cancelled."
    vault.delete_note(note.slug)
    vault.rebuild_index()
    return f"Deleted: {note.name}"


def _cmd_topic_import(filepath: str, topics: TopicManager) -> str:
    if not filepath:
        return "Usage: /topic import <filepath>  (.txt or .json)"
    return topics.import_topics(filepath.strip())


def _cmd_topic_export(status_filter: str, topics: TopicManager) -> str:
    return topics.export_topics(status_filter.strip() or None)


# ── CLI commands ──────────────────────────────────────────────────────────────

def handle_command(cmd: str, memory: MemoryStore, vault: VaultManager, topics: TopicManager, roster: AgentRoster = None) -> str | None:
    parts = cmd.strip().split(maxsplit=1)
    command = parts[0].lower()
    arg = parts[1] if len(parts) > 1 else ""

    if command in ("/exit", "/quit", "/q"):
        count = memory.message_count()
        if count > 2:
            ans = input("Save session summary before exiting? (y/N): ").strip().lower()
            if ans == "y":
                summary = input("Brief description of this session: ").strip()
                if summary:
                    mid = memory.export_session_summary(summary)
                    print(f"Session saved (memory id={mid})")
        print("Goodbye.")
        return None

    elif command == "/help":
        return (
            "\nCommands:\n"
            "  /save [note]            Save session summary to long-term memory\n"
            "  /recall <query>         Search long-term memory\n"
            "  /memory                 Show memory stats\n"
            "  /clear                  Clear conversation history\n"
            "  /forget <id>            Delete a memory by ID\n"
            "\n"
            "  /topic new [name]         Create a research topic\n"
            "  /topic list [status]      List topics\n"
            "  /topic show <name>        Show topic details\n"
            "  /topic queue <name>       Queue a topic for research\n"
            "  /topic archive <name>     Archive a topic\n"
            "  /topic import <file>      Bulk import from .txt or .json\n"
            "  /topic export [status]    Export topics to JSON file\n"
            "  /graph                    Show topic link graph\n"
            "\n"
            "  /context                Print static context (context.md)\n"
            "  /context reload         Reload context.md from disk\n"
            "  /agents                 Show agent roster and model assignments\n"
            "  /agents assign <m> <t>  Assign model to type or topic:slug\n"
            "  /agents clear <m>       Remove model assignments\n"
            "\n"
            "  /model <name>           Switch Ollama model\n"
            "  /models                 List available models\n"
            "  /verbose                Toggle verbose mode\n"
            "  /help                   Show this help\n"
            "  /exit or /quit          Exit\n"
        )

    elif command == "/save":
        note = arg or input("Session summary note: ").strip()
        if note:
            mid = memory.export_session_summary(note)
            return f"Saved to memory (id={mid}): {note}"
        return "Nothing saved (no note provided)."

    elif command == "/recall":
        if not arg:
            return "Usage: /recall <query>"
        results = memory.search_facts(arg)
        if not results:
            return f"No memories found for: {arg}"
        lines = [f"Memory results for '{arg}':"]
        for r in results:
            date = r["created_at"][:10] if r["created_at"] else "?"
            lines.append(f"  [{r['id']}] ({date}) {r['content']}")
            if r.get("tags"):
                lines.append(f"    tags: {r['tags']}")
            if r.get("source_url"):
                lines.append(f"    source: {r['source_url']}")
        return "\n".join(lines)

    elif command == "/memory":
        model = cfg.get("ollama.model")
        host = cfg.get("ollama.base_url")
        total_facts = memory.total_facts()
        total_sources = memory.total_sources()
        total_topics = len(topics.list_topics())
        msgs = memory.message_count()
        verbose = cfg.get("agent.verbose", False)
        vault_path = cfg.get("vault.path", "vault")
        return (
            f"\nMemory stats:\n"
            f"  Long-term memories : {total_facts}\n"
            f"  Sources tracked    : {total_sources}\n"
            f"  Research topics    : {total_topics}\n"
            f"  Session messages   : {msgs}\n"
            f"  Model              : {model}\n"
            f"  Ollama             : {host}\n"
            f"  Vault              : {vault_path}/\n"
            f"  Verbose            : {verbose}\n"
        )

    elif command == "/clear":
        memory.clear_session()
        return "Conversation history cleared."

    elif command == "/forget":
        if not arg or not arg.strip().isdigit():
            return "Usage: /forget <id>  (use /recall to find IDs)"
        mid = int(arg.strip())
        if memory.delete_fact(mid):
            return f"Deleted memory id={mid}"
        return f"Memory id={mid} not found."

    elif command == "/topic":
        return handle_topic_command(arg, vault, topics)

    elif command == "/research":
        if not arg:
            return "Usage: /research <topic_name_or_slug>"
        note = topics.get_topic(arg)
        if not note:
            return f"Topic not found: {arg}. Create it first with /topic new."
        
        print(f"\n[Starting deep research on: {note.name} ({note.type})]")
        from templates import get_research_prompt
        prompt = get_research_prompt(note.type, note.name, note.body)
        
        # Use the assigned model for this topic if one exists
        model = roster.get_model_for(note) if roster else None
        
        run_agent_turn(prompt, memory, vault=vault, topics=topics, roster=roster, forced_model=model)
        beep()
        return f"\n[Research complete for {note.name}]"

    elif command == "/graph":
        return topics.format_topic_graph()

    elif command == "/context":
        if arg.strip().lower() == "reload":
            content = reload_context()
            return f"Context reloaded ({len(content)} chars from {cfg.get('context.path', 'context.md')})."
        content = get_context()
        if not content.strip():
            return "Context file is empty. Edit context.md to add research goals and rules."
        return f"--- Static Context ---\n{content}\n--- End Context ---"

    elif command == "/agents":
        if roster is None:
            return "Agent roster not available."
        sub_parts = arg.strip().split(maxsplit=2)
        sub = sub_parts[0].lower() if sub_parts else ""

        if sub == "assign":
            if len(sub_parts) < 3:
                return "Usage: /agents assign <model> <type|topic:slug>"
            model_name = sub_parts[1]
            target = sub_parts[2]
            if target.startswith("topic:"):
                slug = target[6:]
                roster.assign_topic(model_name, slug)
                return f"Assigned {model_name} to topic: {slug}"
            else:
                roster.assign_type(model_name, target)
                return f"Assigned {model_name} to type: {target}"
        elif sub == "clear":
            if len(sub_parts) < 2:
                return "Usage: /agents clear <model>"
            model_name = sub_parts[1]
            if roster.clear(model_name):
                return f"Cleared assignments for: {model_name}"
            return f"Model not found in roster: {model_name}"
        else:
            return roster.format_roster()

    elif command == "/model":
        if not arg:
            return f"Current model: {cfg.get('ollama.model')} — Usage: /model <name>"
        cfg.set("ollama.model", arg.strip())
        return f"Switched to model: {arg.strip()}"

    elif command == "/models":
        try:
            models = list_models()
            if not models:
                return "No models found on Ollama instance."
            return "Available models:\n" + "\n".join(f"  {m}" for m in models)
        except Exception as e:
            return f"Could not list models: {e}"

    elif command == "/verbose":
        current = cfg.get("agent.verbose", False)
        cfg.set("agent.verbose", not current)
        state = "ON" if not current else "OFF"
        return f"Verbose mode: {state}"

    else:
        return f"Unknown command: {command}  (type /help for commands)"


# ── Startup ───────────────────────────────────────────────────────────────────

_BANNER = """
  ██████╗ ██╗  ██╗ █████╗ ███╗   ██╗████████╗ ██████╗ ███╗   ███╗
  ██╔══██╗██║  ██║██╔══██╗████╗  ██║╚══██╔══╝██╔═══██╗████╗ ████║
  ██████╔╝███████║███████║██╔██╗ ██║   ██║   ██║   ██║██╔████╔██║
  ██╔═══╝ ██╔══██║██╔══██║██║╚██╗██║   ██║   ██║   ██║██║╚██╔╝██║
  ██║     ██║  ██║██║  ██║██║ ╚████║   ██║   ╚██████╔╝██║ ╚═╝ ██║
  ╚═╝     ╚═╝  ╚═╝╚═╝  ╚═╝╚═╝  ╚═══╝   ╚═╝    ╚═════╝ ╚═╝     ╚═╝
                    off-network-agent
"""


def startup() -> tuple[MemoryStore, VaultManager, TopicManager, AgentRoster, bool]:
    print(_BANNER)
    print("=" * 68)
    print("  Phantom Off-Network Agent — Interactive Mode")
    print("=" * 68)

    ok, msg = check_connection()
    if ok:
        print(f"  {msg}")
    else:
        print(f"\n  WARNING: {msg}\n")

    db_path = cfg.get("memory.db_path", "data/memory.db")
    memory = MemoryStore(db_path)

    vault_path = cfg.get("vault.path", "vault")
    vault = VaultManager(vault_path)
    topics = TopicManager(vault)
    roster = AgentRoster()

    load_context()
    ctx_path = cfg.get("context.path", "context.md")

    total_facts = memory.total_facts()
    total_topics = len(topics.list_topics())
    queued = len(topics.list_topics(status="queued"))
    model = cfg.get("ollama.model")

    print(f"  Model   : {model}")
    print(f"  Memories: {total_facts} facts | {total_topics} topics ({queued} queued)")
    print(f"  Vault   : {vault_path}/")
    print(f"  Context : {ctx_path}")
    print(f"  Type /help for commands, /exit to quit")
    print(f"  Flags   : --loop (continuous) | --schedule (batch) | --topic <name> (force)")
    print("=" * 68 + "\n")

    return memory, vault, topics, roster, ok


# ── Main loop ─────────────────────────────────────────────────────────────────

def _start_web_ui():
    """Start the web dashboard in a background daemon thread."""
    try:
        import web_app
        import uvicorn
        print("  Dashboard : http://127.0.0.1:7777", flush=True)
        uvicorn.run(web_app.app, host="127.0.0.1", port=7777,
                    log_level="error", access_log=False)
    except ImportError:
        pass  # fastapi/uvicorn not installed — skip silently
    except Exception as e:
        print(f"  Web UI failed to start: {e}", flush=True)


def _start_background_research(memory, vault, topics, roster):
    """Kick off one research pass immediately on startup in a background thread."""
    import threading
    from scheduler import ResearchScheduler

    def _run():
        try:
            scheduler = ResearchScheduler(memory, vault, topics, roster=roster, max_topics=3)
            scheduler.run()
        except Exception:
            pass

    t = threading.Thread(target=_run, daemon=True, name="startup-research")
    t.start()
    return t


def cli_loop(start_web: bool = True, start_research: bool = True):
    memory, vault, topics, roster, connected = startup()

    # Auto-start dashboard
    if start_web:
        import threading
        web_thread = threading.Thread(target=_start_web_ui, daemon=True, name="web-ui")
        web_thread.start()

    # Immediate background research pass on startup
    if start_research and connected:
        queued = len(topics.list_topics(status="queued"))
        if queued > 0:
            print(f"  Starting background research on {min(queued, 3)} queued topic(s)...", flush=True)
            _start_background_research(memory, vault, topics, roster)

    print()

    while True:
        try:
            user_input = input("You: ").strip()
        except (EOFError, KeyboardInterrupt):
            break

        if not user_input:
            continue

        if user_input.startswith("/"):
            result = handle_command(user_input, memory, vault, topics, roster)
            if result is None:
                break
            print(result)
            continue

        if not connected:
            connected, msg = check_connection()
            if not connected:
                print(f"\nStill can't reach Ollama. {msg}\n")
                continue

        print("\nAgent: ", end="", flush=True)
        try:
            run_agent_turn(user_input, memory, vault=vault, topics=topics, roster=roster)
            beep()
        except OllamaConnectionError as e:
            connected = False
            print(f"\nConnection lost: {e}\n")
        except Exception as e:
            print(f"\nError: {e}\n")
            if cfg.get("agent.verbose", False):
                import traceback
                traceback.print_exc()
        print()

    memory.close()


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Phantom Off-Network Agent")
    parser.add_argument("--schedule", action="store_true",
                        help="Run scheduled research mode — works queue then exits")
    parser.add_argument("--loop", action="store_true",
                        help="Run continuous loop mode — researches forever, weighted by priority+depth")
    parser.add_argument("--topic", metavar="NAME",
                        help="Force-research a specific topic by name then exit")
    parser.add_argument("--no-web", action="store_true",
                        help="Disable auto-start of web dashboard")
    parser.add_argument("--no-autostart", action="store_true",
                        help="Disable immediate background research on startup")
    args = parser.parse_args()

    if args.schedule:
        from scheduler import run_scheduled
        run_scheduled()
    elif args.loop:
        from scheduler import LoopScheduler, _BANNER
        from context import load_context
        from llm import check_connection as _chk
        import threading

        print(_BANNER, flush=True)
        print("=" * 68, flush=True)
        print("  Phantom — Loop Research Mode", flush=True)
        print("=" * 68, flush=True)

        ok, msg = _chk()
        if not ok:
            print(f"\nAborting: {msg}", flush=True)
            sys.exit(1)
        print(f"  {msg}", flush=True)
        load_context()

        db_path = cfg.get("memory.db_path", "data/memory.db")
        vault_path = cfg.get("vault.path", "vault")

        from memory import MemoryStore
        from vault import VaultManager
        from topics import TopicManager
        from agents import AgentRoster

        memory = MemoryStore(db_path)
        vault  = VaultManager(vault_path)
        topics = TopicManager(vault)
        roster = AgentRoster()

        if not args.no_web:
            web_thread = threading.Thread(target=_start_web_ui, daemon=True, name="web-ui")
            web_thread.start()
            import time; time.sleep(0.5)

        loop = LoopScheduler(memory, vault, topics, roster=roster)
        try:
            loop.run()
        except KeyboardInterrupt:
            print("\n\nStopping loop...", flush=True)
            loop.stop()
        memory.close()
    elif args.topic:
        # Force-research a single topic then exit
        from scheduler import _BANNER
        from context import load_context
        from llm import check_connection as _chk
        from memory import MemoryStore
        from vault import VaultManager
        from topics import TopicManager
        from agents import AgentRoster

        print(_BANNER, flush=True)
        ok, msg = _chk()
        if not ok:
            print(f"Aborting: {msg}"); sys.exit(1)
        load_context()

        memory = MemoryStore(cfg.get("memory.db_path", "data/memory.db"))
        vault  = VaultManager(cfg.get("vault.path", "vault"))
        topics = TopicManager(vault)
        roster = AgentRoster()

        note = topics.get_topic(args.topic)
        if not note:
            print(f"Topic not found: {args.topic}"); sys.exit(1)

        print(f"Force-researching: {note.name} (depth {note.research_depth})", flush=True)
        from scheduler import ResearchScheduler
        # Temporarily set topic as queued so scheduler picks it up
        topics.update_status(note.slug, "queued")
        scheduler = ResearchScheduler(memory, vault, topics, roster=roster, max_topics=1)
        scheduler.run()
        memory.close()
    else:
        cli_loop(
            start_web=not args.no_web,
            start_research=not args.no_autostart,
        )
