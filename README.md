# phantom-off-network-agent

> A privacy-first AI research agent that runs entirely on your local hardware.
> No accounts. No cloud. No leaks. Just you, your machine, and the open web.

```
  ██████╗ ██╗  ██╗ █████╗ ███╗   ██╗████████╗ ██████╗ ███╗   ███╗
  ██╔══██╗██║  ██║██╔══██╗████╗  ██║╚══██╔══╝██╔═══██╗████╗ ████║
  ██████╔╝███████║███████║██╔██╗ ██║   ██║   ██║   ██║██╔████╔██║
  ██╔═══╝ ██╔══██║██╔══██║██║╚██╗██║   ██║   ██║   ██║██║╚██╔╝██║
  ██║     ██║  ██║██║  ██║██║ ╚████║   ██║   ╚██████╔╝██║ ╚═╝ ██║
  ╚═╝     ╚═╝  ╚═╝╚═╝  ╚═╝╚═╝  ╚═══╝   ╚═╝    ╚═════╝ ╚═╝     ╚═╝
                    off-network-agent
```

---

## What is this?

Phantom is a ReAct-style AI research agent that:

- **Runs 100% locally** via [Ollama](https://ollama.com) — your gaming PC, your rules
- **Searches the web** via DuckDuckGo — no API key, no tracking, no account
- **Builds a knowledge vault** in [Obsidian](https://obsidian.md)-compatible markdown with live WikiLinks and auto-maintained backlinks
- **Remembers everything** across sessions via SQLite full-text search
- **Works the research queue** automatically — run it on a schedule, come back to a filled vault
- **Assigns models to topics** — route tech questions to codellama, creative research to llama3, etc.

This is a research tool for people who want to think deeply about topics over time, offline from their personal identity.

---

## Features

| Feature | Description |
|---------|-------------|
| **Local LLM** | Ollama backend — llama3, mistral, phi3, any model |
| **Multi-model Routing** | Assign different Ollama models to topic types or individual topics |
| **Curator Broker** | Lightweight broker model auto-selects the best agent for each request |
| **Web Search** | DuckDuckGo — no API key, no rate limits for casual use |
| **Web Fetch** | Full article extraction via trafilatura |
| **Persistent Memory** | SQLite FTS5 — recalls relevant facts before every response |
| **Obsidian Vault** | `.md` notes with YAML frontmatter, WikiLinks, auto backlinks |
| **Topic Management** | Queue, prioritize, archive, and track research topics |
| **Bulk Import/Export** | Load hundreds of topics from a `.txt` or `.json` file |
| **Parallel Scheduler** | `--schedule` runs multiple topics concurrently via ThreadPoolExecutor |
| **Live Progress Output** | Per-topic status lines with ETA during scheduled runs |
| **Structured Logging** | JSONL run logs in `logs/` — every tool call, timing, and error recorded |
| **Vault Stats** | Per-note research run count, source totals, and timing in frontmatter |
| **Daily Digest** | Auto-generated summary of each research run |
| **Conflict Detection** | New findings that contradict existing notes get flagged |
| **Source Registry** | Every URL fetched is tracked with domain and fetch count |
| **Research Templates** | Type-specific prompts: person / tech / event / concept / research |
| **Static Context** | User-editable `context.md` injected into every LLM prompt |
| **Topic Graph** | ASCII forward + backlink map across your entire vault |
| **Dynamic Dashboard** | Modern Web UI with auto-tailing logs and live research progress |

---

## Quick Start

### Prerequisites

- Python 3.10+
- [Ollama](https://ollama.com) installed and running

### Install

```bash
git clone https://github.com/SaltTheFields/phantom-off-network-agent
cd phantom-off-network-agent
pip install -r requirements.txt
pip install fastapi "uvicorn[standard]"  # Optional: for web dashboard
```

### Configure

Edit `config.json` — at minimum set your Ollama address:

```json
{
  "ollama": {
    "base_url": "http://localhost:11434",
    "model": "llama3.2"
  }
}
```

If Ollama is on another machine (e.g. a gaming PC), set `base_url` to its IP and start Ollama with:

```bash
OLLAMA_HOST=0.0.0.0 ollama serve
```

### Run

```bash
# Interactive mode
py agent.py
```
```
  ██████╗ ██╗  ██╗ █████╗ ███╗   ██╗████████╗ ██████╗ ███╗   ███╗
  ██╔══██╗██║  ██║██╔══██╗████╗  ██║╚══██╔══╝██╔═══██╗████╗ ████║
  ██████╔╝███████║███████║██╔██╗ ██║   ██║   ██║   ██║██╔████╔██║
  ██╔═══╝ ██╔══██║██╔══██║██║╚██╗██║   ██║   ██║   ██║██║╚██╔╝██║
  ██║     ██║  ██║██║  ██║██║ ╚████║   ██║   ╚██████╔╝██║ ╚═╝ ██║
  ╚═╝     ╚═╝  ╚═╝╚═╝  ╚═╝╚═╝  ╚═══╝   ╚═╝    ╚═════╝ ╚═╝     ╚═╝
                    off-network-agent

====================================================================
  Phantom Off-Network Agent — Interactive Mode
====================================================================
  Connected to Ollama at http://localhost:11434
  Model   : llama3.1:8b
  ...
```

```bash
# Scheduled research mode (works the queue, then exits)
py agent.py --schedule
```

---

## Web Dashboard

Phantom includes a local, privacy-first web dashboard (default: `http://localhost:7777`) featuring:

- **Live Research Feed**: Real-time tool calls and agent reasoning.
- **Auto-Tailing Log**: Continuous stream of the daily JSONL log.
- **Knowledge Depth**: Visual distribution of your vault's research maturity.
- **Dynamic Accent**: The UI color shifts based on the time of day.
- **Responsive Logo**: The ASCII title animates and glows when active.
- **In-Browser Editor**: Edit note content and metadata directly from the vault view.
- **Full Configuration**: Update `config.json` and `agents.json` without leaving the browser.

---

## How it works

Phantom uses the **ReAct pattern** (Reason + Act). For every message it:

1. Searches long-term memory for relevant context
2. Calls the LLM with your message + context + static context file
3. If the LLM outputs a tool call → executes it → feeds result back
4. Repeats until the LLM gives a final answer (up to 8 iterations)

```
You: "What is the current state of fusion energy?"

  [iter 1] → recall("fusion energy")          → no prior memories
  [iter 2] → web_search("fusion energy 2025")  → 5 results
  [iter 3] → fetch_page("https://...")         → full article text
  [iter 4] → remember("ITER achieved Q>1...")  → saved to SQLite
  [iter 5] → update_note("Fusion Energy", ...) → vault/fusion-energy.md updated
  [final]  → synthesized answer with citations
```

---

## Commands

### Research

| Command | Description |
|---------|-------------|
| `<any message>` | Research and answer — agent uses tools as needed |
| `/research <name>` | Deep research a specific topic now using its template |
| `/save [note]` | Save session summary to long-term memory |
| `/recall <query>` | Search long-term memory directly |
| `/memory` | Show memory stats and current config |
| `/clear` | Clear conversation history |
| `/forget <id>` | Delete a memory by ID |

### Topics & Vault

| Command | Description |
|---------|-------------|
| `/topic new [name]` | Create a new research topic (interactive) |
| `/topic list [status]` | List topics — all, queued, active, archived |
| `/topic show <name>` | Show topic card and note preview |
| `/topic queue <name>` | Move topic back into the research queue |
| `/topic archive <name>` | Archive a completed topic |
| `/topic delete <name>` | Permanently delete a topic |
| `/topic import <file>` | Bulk import from `.txt` or `.json` file |
| `/topic export [status]` | Export topics to a JSON file (re-importable) |
| `/graph` | ASCII topic graph with forward and backlinks |

### Context & Agents

| Command | Description |
|---------|-------------|
| `/context` | Print current static context (`context.md`) |
| `/context reload` | Reload `context.md` from disk without restarting |
| `/agents` | Show model roster with online/offline/VRAM status |
| `/agents assign <model> <type>` | Assign model to all topics of a type |
| `/agents assign <model> topic:<slug>` | Assign model to one specific topic |
| `/agents clear <model>` | Remove all assignments for a model |

### System

| Command | Description |
|---------|-------------|
| `/model <name>` | Switch Ollama model mid-session |
| `/models` | List available models |
| `/verbose` | Toggle tool call visibility |
| `/help` | Show all commands |
| `/exit` | Exit (optionally save session) |

---

## The Vault

Research notes live in `vault/` as Obsidian-compatible markdown:

```
vault/
├── _index.md              ← auto-generated topic index
├── daily/
│   └── 2026-03-29.md     ← research digest from each scheduled run
├── fusion-energy.md
├── sam-altman.md
└── rust-tokio.md
```

Each note has:
- **YAML frontmatter** — status, priority, type, tags, refresh interval, plus cumulative research stats (`research_runs`, `total_sources_fetched`, `last_run_elapsed_s`, etc.)
- **WikiLinks** — `[[Related Topic]]` forward links authored by the agent
- **Auto backlinks** — maintained automatically via `<!-- backlinks-start/end -->` sentinels
- **Conflict warnings** — `> [!warning]` callouts when new research contradicts existing facts

Open the `vault/` folder directly in [Obsidian](https://obsidian.md) for the full graph view.

---

## Bulk Topic Import

Load many topics at once from a plain text or JSON file.

**Text format** (`topics.txt`):
```
Fusion Energy           | tech     | high   | iter, plasma, nuclear | 14
Ada Lovelace            | person   | high   | computing, history    | 30
Byzantine Fault Tolerance | concept | medium | distributed, consensus | 21
```
Fields: `name | type | priority | tags | refresh_days` — all except name are optional.

**JSON format** (`topics.json`):
```json
[
  {"name": "Fusion Energy", "type": "tech", "priority": "high", "tags": ["iter", "plasma"], "refresh_interval_days": 14},
  {"name": "Ada Lovelace", "type": "person", "priority": "high"}
]
```

```
/topic import my-topics.txt

Import preview (3 topics):
  [NEW]   Fusion Energy                 tech      high    14d
  [NEW]   Ada Lovelace                  person    high    30d
  [SKIP]  Byzantine Fault Tolerance     already exists

Create 2 new topics? [y/N]: y
  Created: Fusion Energy
  Created: Ada Lovelace
  Skipped: Byzantine Fault Tolerance

Done. Created: 2 | Skipped: 1 | Errors: 0
```

Export your current topics for editing or sharing:
```
/topic export queued
→ Exported 14 queued topics to: topic-export-queued-2026-03-29.json
```

---

## Scheduled Mode

```bash
py agent.py --schedule
```

```
========================================================
  Phantom — Scheduled Research Mode
  Connected to Ollama at http://localhost:11434
  Queue: 5 queued | 0 stale active | 2 parallel workers
========================================================
Scheduled run: 5 topic(s) | 2 workers
──────────────────────────────────────────────────

[1/5] Fusion Energy                      (tech/high)
       model: llama3.2
       thinking... (iteration 1/8)
       → read_note: Fusion Energy
       thinking... (iteration 2/8)
       → web_search: "fusion energy breakthroughs 2025"
         ✓ 5 result(s) found
       thinking... (iteration 3/8)
       → fetch_page: https://...
         ✓ fetched 3842 chars
       thinking... (iteration 4/8)
       → update_note: writing vault note...
       ── Done [32s] — 2 sources, 1 memories, 4 iterations
       ETA: ~4 remaining, ~2m estimated

[2/5] Ada Lovelace                       (person/high)
       ── Done [28s] — 3 sources, 2 memories, 5 iterations

Rebuilding backlinks...
──────────────────────────────────────────────────
Run complete: 5/5 succeeded | 0 failed | 2m 41s total
Avg per topic: 32s | Vault notes written: 5
Daily digest: vault/daily/2026-03-29.md
──────────────────────────────────────────────────
```

Topics auto-refresh based on `refresh_interval_days` — once a topic's `last_researched` is older than its interval, it gets queued again automatically on the next run.

**Windows Task Scheduler:**
```
Program:   C:\Path\To\Python\python.exe
Arguments: D:\phantom-off-network-agent\agent.py --schedule
Start in:  D:\phantom-off-network-agent
Trigger:   Daily at 3:00 AM
```

---

## Run Logs

Every run writes structured JSONL logs to `logs/phantom-YYYY-MM-DD.log`:

```json
{"ts": "2026-03-29T14:32:07", "level": "INFO", "event": "run_start", "mode": "scheduled", "model": "llama3.2", "queue_size": 14}
{"ts": "2026-03-29T14:32:09", "level": "INFO", "event": "tool_call", "tool": "web_search", "query": "fusion energy breakthroughs 2025", "topic": "fusion-energy"}
{"ts": "2026-03-29T14:32:22", "level": "INFO", "event": "topic_done", "topic": "Fusion Energy", "elapsed_s": 14.2, "sources": 3, "iterations": 5}
{"ts": "2026-03-29T14:45:10", "level": "INFO", "event": "run_done", "topics_completed": 10, "topics_failed": 0, "total_elapsed_s": 252}
```

Logs are auto-rotated after `max_log_age_days` (default: 30 days). `logs/` is gitignored.

---

## Multi-Model Routing

Assign different Ollama models to different research areas:

```
/agents                                   ← show roster with VRAM status
/agents assign mistral tech               ← mistral handles all 'tech' topics
/agents assign llama3.2 research          ← llama3.2 for general research
/agents assign codellama topic:rust-async ← codellama for one specific topic
/agents clear mistral                     ← remove assignments
```

The **CuratorAgent** broker auto-selects the best available model for free-form chat based on capabilities and what's already loaded in VRAM — no model swap penalty if the right model is already hot.

---

## Static Context

Edit `context.md` to give the agent persistent background knowledge injected into every prompt:

```markdown
## Research Goals
Track developments in AI, cybersecurity, and privacy tooling.

## Global Rules
- Always cite sources with direct URLs.
- Flag information older than 1 year as potentially outdated.

## Domain Knowledge
I am a software developer focused on privacy-first local tooling.

## Avoid
- Social media profile pages
- Press releases treated as objective fact
```

```
/context           ← print current context
/context reload    ← pick up edits without restarting
```

---

## Configuration

```json
{
  "ollama": {
    "base_url": "http://192.168.1.50:11434",
    "model": "llama3.2",
    "broker_model": "phi3:mini",
    "timeout": 120,
    "temperature": 0.7
  },
  "vault": {
    "path": "vault",
    "default_refresh_interval_days": 7,
    "conflict_detection": true
  },
  "schedule": {
    "max_topics_per_run": 10,
    "max_parallel_workers": 2,
    "generate_daily_digest": true,
    "stale_check_enabled": true
  },
  "logging": {
    "enabled": true,
    "log_dir": "logs",
    "max_log_age_days": 30
  },
  "memory": {
    "db_path": "data/memory.db",
    "max_short_term_messages": 20
  },
  "context": {
    "path": "context.md"
  },
  "agents": {
    "path": "agents.json"
  }
}
```

---

## Privacy

- **No cloud LLM** — all inference runs on your Ollama instance
- **No accounts** — DuckDuckGo search requires zero authentication
- **No telemetry** — this tool phones home to nothing
- **Local data only** — `data/memory.db`, `vault/`, and `logs/` stay on your machine
- **`.gitignore` guards** — `data/`, `logs/`, and `topic-export*.json` are excluded from version control

---

## Stack

| Component | Library | Why |
|-----------|---------|-----|
| LLM | `ollama` | Local inference, any model |
| Search | `ddgs` | No API key, no account |
| Web fetch | `trafilatura` + `beautifulsoup4` | Best-in-class article extraction |
| Memory | `sqlite3` (stdlib) + FTS5 | Full-text search, WAL concurrent writes |
| Vault | Python stdlib | Hand-rolled YAML parser, no C extensions |
| Logging | `json` (stdlib) | JSONL structured logs, zero deps |
| Tests | `pytest` | 96 tests, all offline |

7 pip packages. No vector database. No API keys. No framework magic.

---

## Running the Tests

```bash
py -m pytest tests/ -v
```

96 tests covering every layer — vault, memory, topics, tools, agents, context, prompts, logging, import/export, and a full end-to-end AI Research pipeline. All tests run offline with a mock LLM.

---

## License

MIT — do whatever you want with it.

---

*Built for people who research things they don't want mixed with their identity.*
