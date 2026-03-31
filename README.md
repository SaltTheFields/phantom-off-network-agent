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
- **Works the research queue automatically** — run it on a schedule, come back to a filled vault
- **Branches autonomously** — every `[[wiki link]]` the agent writes that doesn't exist yet becomes a new queued topic, growing the knowledge graph organically
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
| **Auto-Branching** | New `[[wiki links]]` in research output auto-create queued frontier topics |
| **Bulk Import/Export** | Load hundreds of topics from a `.txt` or `.json` file |
| **Parallel Scheduler** | `--schedule` runs multiple topics concurrently via ThreadPoolExecutor |
| **Loop Mode** | Continuous round-robin research — runs forever, cycles through all topics |
| **Live Progress Output** | Per-topic status lines with ETA during scheduled runs |
| **Structured Logging** | JSONL run logs in `logs/` — every tool call, timing, and error recorded |
| **Vault Stats** | Per-note research run count, source totals, and timing in frontmatter |
| **Daily Digest** | Auto-generated summary of each research run |
| **Conflict Detection** | New findings that contradict existing notes get flagged |
| **Source Registry** | Every URL fetched is tracked with domain and fetch count |
| **Article Cache** | Fetched pages cached in SQLite with timestamps and change-detection diffs |
| **Source Credibility** | Every URL scored by domain tier (academic → gov → quality-news → general) |
| **Research Templates** | Type-specific prompts: person / tech / event / concept / research |
| **Static Context** | User-editable `context.md` injected into every LLM prompt |
| **Interactive Graph** | Force-directed canvas graph — zoom, pan, drag nodes, click to inspect, dbl-click to open |
| **Frontier Nodes** | Ghost nodes show referenced-but-unresearched topics; click to queue them |
| **Semantic Memory** | Sentence-embeddings for hybrid FTS + cosine-similarity memory search |
| **Consensus Mode** | Two-model research + reconciler pass for high-depth topics (opt-in) |
| **Dynamic Dashboard** | Modern Web UI with auto-tailing logs, live research progress, and archived topic toggle |

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
pip install fastapi "uvicorn[standard]" python-multipart  # Optional: for web dashboard
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
  ...
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

# Loop mode (runs continuously, round-robins all topics forever)
py agent.py --loop
```

---

## Web Dashboard

Phantom includes a local, privacy-first web dashboard (default: `http://localhost:7777`):

```bash
py web_app.py
```

Features:
- **Live Research Feed** — real-time tool calls and agent reasoning via SSE
- **Auto-Tailing Log** — continuous stream of the daily JSONL log
- **Knowledge Depth** — visual distribution of vault research maturity
- **Interactive Graph** — force-directed node graph of all topics and their relationships; toggle tag edges, frontier nodes, and labels
- **Vault Browser** — rendered markdown, source credibility scores, wiki links
- **Frontier Pages** — unresearched referenced topics show a "Queue for Research" button
- **In-Browser Editor** — edit note content and metadata without leaving the browser
- **Full Configuration** — update `config.json` and `agents.json` from the Settings page
- **Dynamic Accent** — UI color shifts based on time of day

### Graph

The graph page (`/graph`) shows all vault topics as nodes and their relationships as edges:

- **Link edges** — directed arrows for `[[wiki link]]` citations between notes
- **Tag edges** — dashed purple lines connecting notes that share tags
- **Frontier nodes** — ghost nodes (◌) for topics referenced but not yet researched
- Click a node to inspect it. Double-click to open its vault page.
- Drag to pin nodes. Scroll to zoom. Toggle Labels / Tags / Frontier from the toolbar.

---

## Auto-Branching

Every time the agent writes a note containing `[[Topic Name]]`, Phantom checks whether that topic exists in the vault. If it doesn't, it's automatically created as a queued low-priority topic — inheriting the parent's type and tags. The knowledge graph grows on its own without any manual curation.

You can also visit any frontier URL directly (e.g. `http://localhost:7777/vault/malleus-maleficarum`) and click **Queue for Research** to add it manually.

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
             auto-queued: [[ITER Project]], [[Nuclear Fusion Timeline]]
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
- **YAML frontmatter** — status, priority, type, tags, plus cumulative research stats (`research_runs`, `total_sources_fetched`, `last_run_elapsed_s`, etc.)
- **WikiLinks** — `[[Related Topic]]` forward links authored by the agent
- **Auto backlinks** — maintained automatically via `<!-- backlinks-start/end -->` sentinels
- **Conflict warnings** — `> [!warning]` callouts when new research contradicts existing facts

Open the `vault/` folder directly in [Obsidian](https://obsidian.md) for the full graph view.

---

## Bulk Topic Import

Load many topics at once from a plain text or JSON file.

**Text format** (`topics.txt`):
```
Fusion Energy           | tech     | high   | iter, plasma, nuclear
Ada Lovelace            | person   | high   | computing, history
Byzantine Fault Tolerance | concept | medium | distributed, consensus
```
Fields: `name | type | priority | tags` — all except name are optional.

**JSON format** (`topics.json`):
```json
[
  {"name": "Fusion Energy", "type": "tech", "priority": "high", "tags": ["iter", "plasma"]},
  {"name": "Ada Lovelace", "type": "person", "priority": "high"}
]
```

```
/topic import my-topics.txt

Import preview (3 topics):
  [NEW]   Fusion Energy                 tech      high
  [NEW]   Ada Lovelace                  person    high
  [SKIP]  Byzantine Fault Tolerance     already exists

Create 2 new topics? [y/N]: y
  Created: Fusion Energy
  Created: Ada Lovelace
  Skipped: Byzantine Fault Tolerance

Done. Created: 2 | Skipped: 1 | Errors: 0
```

---

## Scheduled & Loop Mode

```bash
# Run once — works the queue, then exits
py agent.py --schedule

# Run forever — round-robins all topics continuously
py agent.py --loop
```

**Scheduled** mode processes topics once sorted by priority and staleness, then exits. Good for cron / Task Scheduler.

**Loop** mode never exits. It cycles through all topics weighted by priority and depth, sleeping between batches. Topics deepen over time as the agent revisits them, consensus passes kick in at depth ≥ 2, and new topics branch automatically from wiki links discovered during research.

```
========================================================
  Phantom — Loop Mode
  Connected to Ollama at http://localhost:11434
  Pool: 15 topics | Workers: 1
========================================================

[#1 of 15] Fusion Energy                    (tech/high, depth 3)
       model: llama3.1:8b
       thinking... (iteration 1/8)
       → read_note: Fusion Energy
       thinking... (iteration 2/8)
       → web_search: "fusion energy breakthroughs 2026"
         ✓ 5 result(s) found
       → update_note: writing vault note...
         auto-queued: ITER Project, Tokamak Design
       ── Done [32s] — 2 sources, depth 4
```

**Windows Task Scheduler** (for scheduled mode):
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
{"ts": "2026-03-29T14:32:07", "level": "INFO", "event": "run_start", "mode": "loop", "model": "llama3.1:8b", "queue_size": 0}
{"ts": "2026-03-29T14:32:09", "level": "INFO", "event": "tool_call", "tool": "web_search", "query": "fusion energy breakthroughs 2026", "topic": "fusion-energy"}
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

## Semantic Memory

Phantom uses [sentence-transformers](https://www.sbert.net/) (`all-MiniLM-L6-v2`, ~80MB) to give memory search a semantic layer. When you `recall` a fact, results are ranked by a hybrid of full-text keyword match (FTS5 BM25) and cosine similarity between embeddings — so related concepts surface even when exact words don't match.

**First run only**: the model downloads from Hugging Face (~80MB, one-time). After that it's cached locally and loads silently. Nothing is sent to any cloud service.

```bash
py -c "import embeddings; print('semantic search:', embeddings.is_available())"
```

If `sentence-transformers` is not installed, Phantom falls back to keyword-only FTS5 search — no errors, just less fuzz tolerance on recall.

---

## Consensus Mode

Consensus mode runs a topic through **two independent Ollama models** and then uses a third (broker) model to reconcile the outputs. The result tends to be more thorough and self-correcting than a single-model run.

**Off by default.** To enable, pull two models:

```bash
ollama pull llama3.1:8b
ollama pull mistral
```

Then in `config.json`:

```json
"agent": {
  "consensus_mode": true,
  "consensus_min_depth": 2
},
"schedule": {
  "consensus_models": ["llama3.1:8b", "mistral:latest"]
}
```

- `consensus_min_depth` gates the expensive dual-model run — shallow topics use your primary model only.
- `broker_model` reconciles the two outputs. Defaults to `ollama.broker_model` (`phi3:mini` by default).

If you only have one model, leave `consensus_mode: false`.

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
    "model": "llama3.1:8b",
    "broker_model": "phi3:mini",
    "timeout": 600,
    "temperature": 0.7
  },
  "agent": {
    "consensus_mode": false,
    "consensus_min_depth": 2
  },
  "vault": {
    "path": "vault",
    "conflict_detection": true
  },
  "schedule": {
    "max_topics_per_run": 10,
    "max_parallel_workers": 1,
    "consensus_models": ["llama3.1:8b", "mistral:latest"],
    "generate_daily_digest": true,
    "stale_check_enabled": true,
    "loop_batch_size": 3,
    "loop_sleep_between_topics_s": 30,
    "loop_batch_rest_s": 120
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
  "context": { "path": "context.md" },
  "agents": { "path": "agents.json" },
  "web": { "host": "127.0.0.1", "port": 7777 }
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
| Semantic search | `sentence-transformers` | Hybrid embedding + keyword recall (~80MB, one-time) |
| Web dashboard | `fastapi` + `uvicorn` + `python-multipart` | Live SSE feed, vault editor, config UI |
| Vault | Python stdlib | Hand-rolled YAML parser, no C extensions |
| Logging | `json` (stdlib) | JSONL structured logs, zero deps |
| Tests | `pytest` | Offline test suite with mock LLM |

No vector database. No API keys. No cloud calls. All inference stays on your machine.

---

## Running the Tests

```bash
py -m pytest tests/ -v
```

Covers vault, memory, topics, tools, agents, context, prompts, logging, import/export, and a full end-to-end pipeline. All tests run offline with a mock LLM.

---

## License

MIT — do whatever you want with it.

---

*Built for people who research things they don't want mixed with their identity.*
