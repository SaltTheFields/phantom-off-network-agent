"""
Phantom Web UI — local dashboard for the Off-Network Agent.

Run with:
    python web_app.py
    # Opens http://localhost:7777

Extra dependencies:
    pip install fastapi "uvicorn[standard]"

Everything else (vault, topics, memory, agents, config) imports
from the project directory automatically.
"""

import os
import sys
import html as _html
import threading
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

try:
    from fastapi import FastAPI, Request
    from fastapi.responses import HTMLResponse, RedirectResponse
    import uvicorn
except ImportError:
    print("Missing dependencies. Run:  pip install fastapi \"uvicorn[standard]\"")
    sys.exit(1)

from config import cfg
from vault import VaultManager
from topics import TopicManager
from memory import MemoryStore

app = FastAPI(title="Phantom Agent", docs_url=None, redoc_url=None)

_vault = VaultManager(cfg.get("vault.path", "vault"))
_topics = TopicManager(_vault)
_memory = MemoryStore(cfg.get("memory.db_path", "data/memory.db"))
_run_status: dict = {"running": False, "last": ""}

# ── HTML base ─────────────────────────────────────────────────────────────────

_CSS = """
<style>
* { box-sizing: border-box; margin: 0; padding: 0; }
body { background: #0e0e0e; color: #d4d4d4; font-family: 'Consolas','Courier New',monospace; font-size: 14px; }
a { color: #7ec8e3; text-decoration: none; }
a:hover { color: #b0e0ff; text-decoration: underline; }
nav { background: #1a1a1a; padding: 12px 24px; border-bottom: 1px solid #333; display: flex; gap: 24px; align-items: center; }
nav .brand { color: #7ec8e3; font-weight: bold; font-size: 16px; margin-right: 12px; }
nav a { color: #aaa; }
nav a.active, nav a:hover { color: #fff; }
.container { padding: 24px; max-width: 1100px; margin: 0 auto; }
h1 { color: #fff; font-size: 20px; margin-bottom: 18px; }
h2 { color: #ccc; font-size: 15px; margin: 22px 0 10px; border-bottom: 1px solid #222; padding-bottom: 6px; }
.stats { display: flex; gap: 14px; margin-bottom: 24px; flex-wrap: wrap; }
.stat { background: #1a1a1a; border: 1px solid #2e2e2e; padding: 12px 18px; border-radius: 4px; min-width: 110px; }
.stat .lbl { color: #666; font-size: 11px; text-transform: uppercase; margin-bottom: 4px; }
.stat .val { color: #7ec8e3; font-size: 24px; font-weight: bold; }
table { width: 100%; border-collapse: collapse; margin-bottom: 20px; }
th { text-align: left; color: #666; font-size: 11px; text-transform: uppercase; padding: 6px 10px; border-bottom: 1px solid #222; }
td { padding: 8px 10px; border-bottom: 1px solid #1a1a1a; vertical-align: top; }
tr:hover td { background: #141414; }
.b { display: inline-block; padding: 2px 8px; border-radius: 10px; font-size: 11px; font-weight: bold; }
.b-high   { background: #3a1a1a; color: #ff6b6b; }
.b-medium { background: #2a2a1a; color: #ffd93d; }
.b-low    { background: #1a2a1a; color: #6bcb77; }
.b-queued { background: #1a2030; color: #7ec8e3; }
.b-active { background: #1a2a1a; color: #6bcb77; }
.b-archived { background: #222; color: #666; }
form { display: inline; }
button, input[type=submit] { background: #1e3040; color: #7ec8e3; border: 1px solid #2e4a5e; padding: 5px 14px; cursor: pointer; font-family: inherit; font-size: 13px; border-radius: 3px; }
button:hover, input[type=submit]:hover { background: #2a4a60; }
.btn-sm { padding: 2px 8px; font-size: 11px; }
.btn-danger { background: #3a1a1a; color: #ff6b6b; border-color: #5e2e2e; }
.btn-danger:hover { background: #5a2a2a; }
input[type=text], select { background: #1a1a1a; color: #d4d4d4; border: 1px solid #333; padding: 6px 10px; font-family: inherit; font-size: 13px; border-radius: 3px; }
input[type=text]:focus, select:focus { outline: none; border-color: #7ec8e3; }
.row { display: flex; gap: 10px; align-items: center; margin-bottom: 10px; flex-wrap: wrap; }
.row label { color: #888; min-width: 80px; }
pre { background: #111; padding: 16px; overflow-x: auto; border-radius: 4px; border: 1px solid #222; white-space: pre-wrap; word-break: break-word; line-height: 1.5; max-height: 600px; overflow-y: auto; }
.tag { display: inline-block; background: #1e1e1e; color: #777; padding: 1px 6px; border-radius: 3px; font-size: 11px; margin: 1px; }
.alert { padding: 10px 16px; border-radius: 4px; margin-bottom: 16px; border: 1px solid; }
.alert-info  { background: #1a2030; border-color: #2e4a5e; color: #7ec8e3; }
.alert-ok    { background: #1a2a1a; border-color: #2e5e2e; color: #6bcb77; }
.alert-warn  { background: #2a2a1a; border-color: #5e5e2e; color: #ffd93d; }
.empty { color: #444; font-style: italic; padding: 16px 0; }
details summary { cursor: pointer; color: #7ec8e3; padding: 6px 0; user-select: none; }
.meta-grid { background: #1a1a1a; border: 1px solid #2a2a2a; padding: 14px; border-radius: 4px; margin-bottom: 18px; display: grid; grid-template-columns: 1fr 1fr; gap: 8px 24px; }
.meta-grid span.lbl { color: #666; }
.log-entry { font-size: 12px; color: #666; border-bottom: 1px solid #161616; padding: 3px 0; overflow: hidden; white-space: nowrap; text-overflow: ellipsis; }
.log-entry.err { color: #ff6b6b; }
</style>
"""


def _nav(active: str = "") -> str:
    pages = [("/", "Dashboard"), ("/vault", "Vault"), ("/topics", "Topics"),
             ("/memory", "Memory"), ("/agents", "Agents")]
    items = "".join(
        f'<a href="{h}" class="{"active" if label.lower() == active else ""}">{label}</a>'
        for h, label in pages
    )
    return f'<nav><span class="brand">⬡ Phantom</span>{items}</nav>'


def _badge(text: str) -> str:
    return f'<span class="b b-{text.lower()}">{text}</span>'


def _page(title: str, body: str, active: str = "") -> HTMLResponse:
    return HTMLResponse(
        f'<!DOCTYPE html><html><head><meta charset="utf-8">'
        f'<title>{title} — Phantom</title>{_CSS}</head>'
        f'<body>{_nav(active)}<div class="container">{body}</div></body></html>'
    )


# ── Dashboard ─────────────────────────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
def dashboard():
    all_notes = _topics.list_topics()
    queued  = [n for n in all_notes if n.status == "queued"]
    active  = [n for n in all_notes if n.status == "active"]
    archived = [n for n in all_notes if n.status == "archived"]

    stats = "".join(
        f'<div class="stat"><div class="lbl">{lbl}</div><div class="val">{val}</div></div>'
        for lbl, val in [
            ("Queued", len(queued)), ("Active", len(active)), ("Archived", len(archived)),
            ("Memories", _memory.total_facts()), ("Sources", _memory.total_sources()),
        ]
    )

    run_btn = '<form method="post" action="/run" style="margin-bottom:20px"><button>▶ Run Schedule Now</button></form>'
    if _run_status["running"]:
        run_btn = '<div class="alert alert-warn">⏳ Scheduled run in progress…</div>'
    elif _run_status["last"]:
        run_btn += f'<div class="alert alert-info">{_html.escape(_run_status["last"])}</div>'

    PRIO = {"high": 0, "medium": 1, "low": 2}
    rows = "".join(
        f'<tr><td><a href="/vault/{n.slug}">{_html.escape(n.name)}</a></td>'
        f'<td>{_badge(n.priority)}</td><td style="color:#777">{n.type}</td>'
        f'<td>{"".join(f"<span class=tag>{_html.escape(t)}</span>" for t in n.tags)}</td>'
        f'<td style="color:#555">{n.created}</td></tr>'
        for n in sorted(queued, key=lambda n: (PRIO.get(n.priority, 1), n.created))
    ) or '<tr><td colspan="5" class="empty">Queue is empty</td></tr>'

    queue = (
        f'<h2>Research Queue ({len(queued)})</h2>'
        f'<table><thead><tr><th>Topic</th><th>Priority</th><th>Type</th><th>Tags</th><th>Created</th></tr></thead>'
        f'<tbody>{rows}</tbody></table>'
    )

    # Today's log
    log_html = ""
    log_path = f"logs/phantom-{date.today()}.log"
    if os.path.exists(log_path):
        with open(log_path, encoding="utf-8", errors="replace") as f:
            lines = [l.rstrip() for l in f if l.strip().startswith("{")]
        recent = lines[-20:]
        entries = "".join(
            f'<div class="log-entry {"err" if "ERROR" in l or "FAIL" in l else ""}">{_html.escape(l[:220])}</div>'
            for l in reversed(recent)
        ) or '<span class="empty">No entries yet</span>'
        log_html = (
            f'<h2>Today\'s Log</h2>'
            f'<div style="background:#111;padding:10px;border:1px solid #222;border-radius:4px;max-height:260px;overflow-y:auto">'
            f'{entries}</div>'
        )

    return _page("Dashboard", f'<h1>Dashboard</h1>{run_btn}<div class="stats">{stats}</div>{queue}{log_html}', "dashboard")


# ── Vault list ────────────────────────────────────────────────────────────────

@app.get("/vault", response_class=HTMLResponse)
def vault_list():
    notes = sorted(_topics.list_topics(), key=lambda n: n.name)
    rows = "".join(
        f'<tr><td><a href="/vault/{n.slug}">{_html.escape(n.name)}</a></td>'
        f'<td>{_badge(n.status)}</td><td>{_badge(n.priority)}</td>'
        f'<td style="color:#777">{n.type}</td>'
        f'<td style="color:#666">{n.last_researched or "never"}</td>'
        f'<td style="color:#7ec8e3">{n.research_runs or ""}</td>'
        f'<td style="color:#666">{n.total_sources_fetched or ""}</td></tr>'
        for n in notes
    ) or '<tr><td colspan="7" class="empty">Vault is empty</td></tr>'

    body = (
        f'<h1>Vault ({len(notes)} notes)</h1>'
        f'<table><thead><tr><th>Name</th><th>Status</th><th>Priority</th><th>Type</th>'
        f'<th>Last Researched</th><th>Runs</th><th>Sources</th></tr></thead>'
        f'<tbody>{rows}</tbody></table>'
    )
    return _page("Vault", body, "vault")


# ── Note detail ───────────────────────────────────────────────────────────────

@app.get("/vault/{slug}", response_class=HTMLResponse)
def vault_note(slug: str):
    note = _vault.read_note(slug)
    if not note:
        return _page("Not Found", f'<div class="alert alert-warn">Note not found: {slug}</div>', "vault")

    tags  = "".join(f'<span class="tag">{_html.escape(t)}</span>' for t in note.tags) or "<span style='color:#555'>none</span>"
    feeds = "".join(f'<span class="tag">{_html.escape(f)}</span>' for f in (note.feeds or [])) or "<span style='color:#555'>none</span>"
    fwd   = ", ".join(
        f'<a href="/vault/{_vault.name_to_slug(l)}">{_html.escape(l)}</a>'
        for l in note.forward_links
    ) or "<span style='color:#555'>none</span>"

    meta = (
        '<div class="meta-grid">'
        f'<div><span class="lbl">Status</span>  {_badge(note.status)}</div>'
        f'<div><span class="lbl">Priority</span> {_badge(note.priority)}</div>'
        f'<div><span class="lbl">Type</span>     <span>{note.type}</span></div>'
        f'<div><span class="lbl">Created</span>  <span>{note.created}</span></div>'
        f'<div><span class="lbl">Researched</span> <span>{note.last_researched or "never"}</span></div>'
        f'<div><span class="lbl">Refresh</span>  <span>every {note.refresh_interval_days}d</span></div>'
        f'<div><span class="lbl">Runs</span>     <span style="color:#7ec8e3">{note.research_runs}</span></div>'
        f'<div><span class="lbl">Sources</span>  <span style="color:#7ec8e3">{note.total_sources_fetched}</span></div>'
        f'<div style="grid-column:1/-1"><span class="lbl">Tags</span>  {tags}</div>'
        f'<div style="grid-column:1/-1"><span class="lbl">Links to</span> {fwd}</div>'
        f'<div style="grid-column:1/-1"><span class="lbl">Feeds</span> {feeds}</div>'
        '</div>'
    )

    actions = (
        '<div style="display:flex;gap:8px;margin-bottom:16px">'
        f'<form method="post" action="/topics/{note.slug}/queue"><button>↺ Requeue</button></form>'
        f'<form method="post" action="/topics/{note.slug}/archive"><button class="btn-danger">Archive</button></form>'
        '<a href="/vault"><button>← Back</button></a>'
        '</div>'
    )

    body = (
        f'<h1>{_html.escape(note.name)}</h1>'
        f'{actions}{meta}'
        f'<h2>Note Content</h2>'
        f'<pre>{_html.escape(note.body or "")}</pre>'
    )
    return _page(note.name, body, "vault")


# ── Topics ────────────────────────────────────────────────────────────────────

@app.get("/topics", response_class=HTMLResponse)
def topics_list(status: str = "all"):
    filter_bar = " ".join(
        f'<a href="/topics?status={s}" style="{"color:#fff" if s==status else ""}">{s}</a>'
        for s in ["all", "queued", "active", "archived"]
    )

    notes = _topics.list_topics(status=status if status != "all" else None)
    PRIO = {"high": 0, "medium": 1, "low": 2}
    notes = sorted(notes, key=lambda n: (PRIO.get(n.priority, 1), n.name))

    rows = "".join(
        f'<tr><td><a href="/vault/{n.slug}">{_html.escape(n.name)}</a></td>'
        f'<td>{_badge(n.status)}</td><td>{_badge(n.priority)}</td>'
        f'<td style="color:#777">{n.type}</td>'
        f'<td>{"".join(f"<span class=tag>{_html.escape(t)}</span>" for t in n.tags)}</td>'
        f'<td style="color:#555">{n.last_researched or "never"}</td>'
        f'<td style="color:#555">{n.refresh_interval_days}d</td>'
        f'<td>'
        f'<form method="post" action="/topics/{n.slug}/queue"><button class="btn-sm">↺</button></form> '
        f'<form method="post" action="/topics/{n.slug}/archive"><button class="btn-sm btn-danger">✕</button></form>'
        f'</td></tr>'
        for n in notes
    ) or '<tr><td colspan="8" class="empty">No topics found</td></tr>'

    new_form = (
        '<details style="margin-top:20px"><summary>+ New Topic</summary>'
        '<form method="post" action="/topics/new" '
        'style="margin-top:12px;background:#1a1a1a;padding:16px;border:1px solid #2a2a2a;border-radius:4px">'
        '<div class="row"><label>Name</label><input type="text" name="name" required style="width:280px"></div>'
        '<div class="row"><label>Type</label>'
        '<select name="type"><option>research</option><option>tech</option><option>person</option>'
        '<option>event</option><option>concept</option></select>'
        '<label style="margin-left:16px">Priority</label>'
        '<select name="priority"><option>medium</option><option>high</option><option>low</option></select></div>'
        '<div class="row"><label>Tags</label><input type="text" name="tags" placeholder="comma separated"></div>'
        '<div class="row"><input type="submit" value="Create Topic"></div>'
        '</form></details>'
    )

    body = (
        f'<h1>Topics</h1>'
        f'<div style="margin-bottom:14px;color:#777">Filter: {filter_bar}</div>'
        f'<table><thead><tr><th>Name</th><th>Status</th><th>Priority</th><th>Type</th>'
        f'<th>Tags</th><th>Last Researched</th><th>Refresh</th><th></th></tr></thead>'
        f'<tbody>{rows}</tbody></table>'
        f'{new_form}'
    )
    return _page("Topics", body, "topics")


@app.post("/topics/new")
async def new_topic(request: Request):
    form = await request.form()
    name  = str(form.get("name", "")).strip()
    ttype = str(form.get("type", "research"))
    prio  = str(form.get("priority", "medium"))
    tags  = [t.strip() for t in str(form.get("tags", "")).split(",") if t.strip()]
    if name:
        try:
            _topics.create_topic(name, type=ttype, priority=prio, tags=tags)
        except ValueError:
            pass
    return RedirectResponse("/topics", status_code=303)


@app.post("/topics/{slug}/queue")
def queue_topic(slug: str):
    _topics.update_status(slug, "queued")
    return RedirectResponse(f"/vault/{slug}", status_code=303)


@app.post("/topics/{slug}/archive")
def archive_topic_route(slug: str):
    _topics.archive_topic(slug)
    return RedirectResponse("/topics", status_code=303)


# ── Memory search ─────────────────────────────────────────────────────────────

@app.get("/memory", response_class=HTMLResponse)
def memory_page(q: str = ""):
    stats = (
        '<div class="stats">'
        f'<div class="stat"><div class="lbl">Total Facts</div><div class="val">{_memory.total_facts()}</div></div>'
        f'<div class="stat"><div class="lbl">Total Sources</div><div class="val">{_memory.total_sources()}</div></div>'
        '</div>'
    )

    search = (
        f'<form method="get" action="/memory" style="display:flex;gap:8px;margin-bottom:20px">'
        f'<input type="text" name="q" value="{_html.escape(q)}" placeholder="Search memories…" style="width:380px">'
        f'<input type="submit" value="Search"></form>'
    )

    if q:
        results = _memory.hybrid_search(q, limit=20)
        rows = "".join(
            f'<tr><td style="color:#555">{r["id"]}</td>'
            f'<td>{_html.escape(r["content"][:300])}'
            f'{"<span style=color:#666;font-size:11px> [sim:" + str(round(r.get("semantic_score",0),2)) + "]</span>" if r.get("semantic_score") else ""}'
            f'</td><td><span class="tag">{_html.escape(r.get("tags",""))}</span></td>'
            f'<td style="color:#555">{(r["created_at"] or "")[:10]}</td></tr>'
            for r in results
        ) or f'<tr><td colspan="4" class="empty">No results for "{_html.escape(q)}"</td></tr>'
        results_html = (
            f'<h2>Results for "{_html.escape(q)}" ({len(results) if results else 0})</h2>'
            f'<table><thead><tr><th>ID</th><th>Content</th><th>Tags</th><th>Date</th></tr></thead>'
            f'<tbody>{rows}</tbody></table>'
        )
    else:
        recent = _memory.get_recent_facts(limit=25)
        rows = "".join(
            f'<tr><td style="color:#555">{r["id"]}</td>'
            f'<td>{_html.escape(r["content"][:300])}</td>'
            f'<td><span class="tag">{_html.escape(r.get("tags",""))}</span></td>'
            f'<td style="color:#555">{(r["created_at"] or "")[:10]}</td></tr>'
            for r in recent
        ) or '<tr><td colspan="4" class="empty">No memories yet</td></tr>'
        results_html = (
            '<h2>Recent Memories</h2>'
            '<table><thead><tr><th>ID</th><th>Content</th><th>Tags</th><th>Date</th></tr></thead>'
            f'<tbody>{rows}</tbody></table>'
        )

    return _page("Memory", f'<h1>Memory</h1>{stats}{search}{results_html}', "memory")


# ── Agents ────────────────────────────────────────────────────────────────────

@app.get("/agents", response_class=HTMLResponse)
def agents_page():
    try:
        from agents import AgentRoster
        roster = AgentRoster()
        available = roster.list_available()
    except Exception as e:
        return _page("Agents", f'<div class="alert alert-warn">Could not load roster: {_html.escape(str(e))}</div>', "agents")

    rows = "".join(
        f'<tr><td><strong>{_html.escape(a["model"])}</strong>'
        f'{"<span style=color:#666> (" + _html.escape(a["nickname"]) + ")</span>" if a.get("nickname") else ""}'
        f'</td>'
        f'<td style="color:{"#6bcb77" if a["loaded"] else "#7ec8e3" if a["available"] else "#ff6b6b"}">'
        f'{"HOT" if a["loaded"] else "online" if a["available"] else "offline"}</td>'
        f'<td>{_html.escape(", ".join(a["assigned_types"]) or "—")}</td>'
        f'<td>{_html.escape(", ".join(a["capabilities"]) or "—")}</td>'
        f'<td style="color:#777">{_html.escape(a.get("description",""))}</td></tr>'
        for a in available
    ) or '<tr><td colspan="5" class="empty">No models found — is Ollama running?</td></tr>'

    default = cfg.get("ollama.model", "unknown")
    body = (
        f'<h1>Agent Roster</h1>'
        f'<div class="alert alert-info">Default model: <strong>{_html.escape(default)}</strong></div>'
        f'<p style="color:#666;margin-bottom:16px;font-size:12px">Use <code>/agents assign</code> in the CLI to modify assignments.</p>'
        f'<table><thead><tr><th>Model</th><th>Status</th><th>Assigned Types</th><th>Capabilities</th><th>Description</th></tr></thead>'
        f'<tbody>{rows}</tbody></table>'
    )
    return _page("Agents", body, "agents")


# ── Schedule trigger ──────────────────────────────────────────────────────────

@app.post("/run")
def trigger_run():
    if _run_status["running"]:
        _run_status["last"] = "A run is already in progress."
        return RedirectResponse("/", status_code=303)

    def _do():
        _run_status["running"] = True
        try:
            from scheduler import ResearchScheduler
            from agents import AgentRoster
            mem = MemoryStore(cfg.get("memory.db_path", "data/memory.db"))
            vault = VaultManager(cfg.get("vault.path", "vault"))
            topics = TopicManager(vault)
            roster = AgentRoster()
            result = ResearchScheduler(mem, vault, topics, roster=roster).run()
            _run_status["last"] = (
                f"Run complete: {result.topics_succeeded} succeeded, {result.topics_failed} failed."
            )
            mem.close()
        except Exception as e:
            _run_status["last"] = f"Run error: {e}"
        finally:
            _run_status["running"] = False

    threading.Thread(target=_do, daemon=True).start()
    return RedirectResponse("/", status_code=303)


# ── Entry ─────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("\n  Phantom Web UI  →  http://127.0.0.1:7777\n")
    uvicorn.run(app, host="127.0.0.1", port=7777, log_level="warning")
