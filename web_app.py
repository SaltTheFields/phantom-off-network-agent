"""
Phantom Web UI — local dashboard for the Off-Network Agent.

Run with:
    python web_app.py          →  http://localhost:7777

Extra dependencies:
    pip install fastapi "uvicorn[standard]"
"""

import os
import sys
import html as _html
import json
import queue
import threading
import time as _time
from datetime import date, datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

try:
    from fastapi import FastAPI, Request
    from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, StreamingResponse
    import uvicorn
except ImportError:
    print("Missing deps: pip install fastapi \"uvicorn[standard]\"")
    sys.exit(1)

from config import cfg
from vault import VaultManager
from topics import TopicManager
from memory import MemoryStore

app = FastAPI(title="Phantom Agent", docs_url=None, redoc_url=None)

_vault  = VaultManager(cfg.get("vault.path", "vault"))
_topics = TopicManager(_vault)
_memory = MemoryStore(cfg.get("memory.db_path", "data/memory.db"))

_run_status: dict = {
    "running":      False,
    "last":         "",
    "active_topic": "",
    "active_model": "",
    "active_step":  "",
    "started_at":   "",    # ISO string for JS timer
    "started_ts":   0.0,   # time.time() for server-side elapsed
}

_sse_subscribers: list[queue.Queue] = []
_sse_lock = threading.Lock()


def _broadcast(msg: str):
    with _sse_lock:
        dead = []
        for q in _sse_subscribers:
            try:
                q.put_nowait(msg)
            except queue.Full:
                dead.append(q)
        for q in dead:
            _sse_subscribers.remove(q)


def _broadcast_event(data: dict):
    """Convert a PhantomLogger event dict into a human-readable SSE line and update run status."""
    ev    = data.get("event", "")
    topic = data.get("topic", data.get("slug", ""))
    
    # Update global run status for dashboard visibility
    if ev == "topic_start":
        _run_status["active_topic"] = topic
        if "model" in data:
            _run_status["active_model"] = data["model"]
    elif ev == "topic_done" or ev == "topic_failed":
        if _run_status.get("active_topic") == topic:
            _run_status["active_topic"] = ""
    elif ev == "run_start":
        _run_status["running"] = True
        _run_status["started_ts"] = _time.time()
        _run_status["started_at"] = datetime.now().strftime("%H:%M:%S")
        if "model" in data:
            _run_status["active_model"] = data["model"]
    elif ev == "run_done":
        _run_status["running"] = False
        _run_status["active_topic"] = ""
        _run_status["active_model"] = ""

    if ev == "run_start":
        msg = f">> run started  model={data.get('model','')}  queue={data.get('queue_size','')}"
    elif ev == "run_done":
        msg = (f"== run done  ok={data.get('topics_completed',0)}"
               f"  fail={data.get('topics_failed',0)}  {data.get('total_elapsed_s','')}s")
    elif ev == "topic_start":
        msg = (f"-> [{data.get('position','')}/{data.get('of','')}] {topic}"
               f"  {data.get('priority','')} {data.get('type','')}")
    elif ev == "topic_done":
        msg = (f"ok {topic}"
               f"  {data.get('elapsed_s','')}s  src={data.get('sources',0)}"
               f"  mem={data.get('memories',0)}  iter={data.get('iterations',0)}")
    elif ev == "topic_failed":
        msg = f"!! {topic}  {data.get('error','')}"
    elif ev == "tool_call":
        msg = f"   tool:{data.get('tool','')}  {topic}"
        _run_status["active_step"] = f"Using {data.get('tool','')}"
    elif ev == "tool_result":
        msg = f"   done:{data.get('tool','')}  {data.get('elapsed_ms','')}ms"
        _run_status["active_step"] = f"Finished {data.get('tool','')}"
    elif ev == "note_written":
        msg = f"   note saved  {data.get('slug','')}  src={data.get('sources',0)}"
    elif ev == "memory_saved":
        msg = f"   memory #{data.get('memory_id','')} stored"
    elif ev == "warn":
        msg = f"!! warn  {json.dumps(data)}"
    else:
        msg = f"   {ev}  {topic}"
    _broadcast(msg)


def _hook_scheduler_log(scheduler):
    """Patch scheduler.log so every event is also broadcast to the live feed."""
    scheduler.log._on_event = _broadcast_event


# Register as global hook so CLI-launched loop schedulers also stream to browser.
# Must be after _broadcast_event is defined.
import logger as _logger_mod
_logger_mod.register_global_hook(_broadcast_event)


# ── ASCII Banner ───────────────────────────────────────────────────────────────

_BANNER = (
    r"  ____  _   _    _    _   _ _____ ___  __  __" + "\n"
    r" |  _ \| | | |  / \  | \ | |_   _/ _ \|  \/  |" + "\n"
    r" | |_) | |_| | / _ \ |  \| | | || | | | |\/| |" + "\n"
    r" |  __/|  _  |/ ___ \| |\  | | || |_| | |  | |" + "\n"
    r" |_|   |_| |_/_/   \_\_| \_| |_| \___/|_|  |_|" + "\n"
    r" ················· off-network-agent ···········"
)


# ── Styles ─────────────────────────────────────────────────────────────────────

_CSS = """<style>
:root {
  --accent-h: 200;
  --accent: hsl(200,68%,62%);
  --accent-bright: hsl(200,80%,74%);
  --accent-dim: hsl(200,45%,38%);
  --accent-bg: hsl(200,28%,9%);
  --accent-border: hsl(200,35%,16%);
  --accent-grad: linear-gradient(90deg,hsl(200,70%,58%),hsl(250,70%,70%),hsl(200,70%,58%));
}
*{box-sizing:border-box;margin:0;padding:0}
body{background:#0b0b0b;color:#c8c8c8;font-family:'Consolas','Courier New',monospace;font-size:13px}
a{color:var(--accent);text-decoration:none}
a:hover{color:var(--accent-bright);text-decoration:underline}

/* ── Banner ── */
.banner-wrap{
  background:#080808;
  border-bottom:1px solid #181818;
  padding:12px 24px 8px;
  overflow:hidden;
  position: relative;
}
.banner-wrap.running::after {
  content: '';
  position: absolute;
  top: 0; left: 0; right: 0; bottom: 0;
  background: radial-gradient(circle at center, var(--accent-bg) 0%, transparent 70%);
  opacity: 0.3;
  pointer-events: none;
  animation: pulseBg 4s ease-in-out infinite;
}
@keyframes pulseBg { 0%, 100% { opacity: 0.1; } 50% { opacity: 0.4; } }

.banner{
  display:inline-block;
  font-size:13px;
  line-height:1.3;
  letter-spacing:.02em;
  white-space:pre;
  font-weight:bold;
  background:var(--accent-grad);
  background-size:250% auto;
  -webkit-background-clip:text;
  -webkit-text-fill-color:transparent;
  background-clip:text;
  animation:bannerFlow 8s linear infinite;
  user-select:none;
}
.banner-wrap.running .banner {
  animation: bannerFlow 3s linear infinite, glow 2s ease-in-out infinite alternate;
  filter: drop-shadow(0 0 5px var(--accent-dim));
}
@keyframes bannerFlow{0%{background-position:0% center}100%{background-position:250% center}}
@keyframes glow { from { filter: drop-shadow(0 0 2px var(--accent-dim)); } to { filter: drop-shadow(0 0 8px var(--accent-bright)); } }

.banner-sub{
  font-size:10px;
  color:var(--accent-dim);
  margin-top:2px;
  padding-left:2px;
  letter-spacing:.2em;
  text-transform: uppercase;
}

/* ── Layout ── */
.container{padding:18px 24px;max-width:1440px;margin:0 auto}
h1{color:#fff;font-size:18px;margin-bottom:16px;letter-spacing:.05em; border-left: 4px solid var(--accent); padding-left: 12px;}
h2{
  color:var(--accent);font-size:11px;text-transform:uppercase;letter-spacing:.15em;
  margin:24px 0 10px;padding-bottom:6px;
  border-bottom:1px solid var(--accent-border);
  display:flex;align-items:center;gap:8px;
}
h2 .h2-count{color:#444;font-size:10px; font-weight: normal;}

/* ── Stat cards ── */
.stats{display:flex;gap:12px;margin-bottom:20px;flex-wrap:wrap}
.stat{
  background:#0f0f0f;border:1px solid #1c1c1c;
  padding:12px 18px;border-radius:6px;min-width:120px;
  transition: all .3s cubic-bezier(0.4, 0, 0.2, 1);
  box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.1);
}
.stat:hover{border-color:var(--accent); transform: translateY(-2px); box-shadow: 0 10px 15px -3px rgba(0, 0, 0, 0.2);}
.stat .lbl{color:#555;font-size:10px;text-transform:uppercase;letter-spacing:.1em;margin-bottom:6px}
.stat .val{color:var(--accent);font-size:24px;font-weight:bold;line-height:1; text-shadow: 0 0 10px rgba(var(--accent-h), 68%, 62%, 0.2);}

/* ── Active panel ── */
.active-panel{
  background:var(--accent-bg);
  border:1px solid var(--accent-border);
  border-left:4px solid var(--accent);
  border-radius:6px;
  padding:14px 18px;
  margin-bottom:20px;
  animation: borderGlow 2s infinite alternate;
}
@keyframes borderGlow { from { border-color: var(--accent-border); } to { border-color: var(--accent); } }
.active-panel .ap-label{color:var(--accent);font-size:11px;text-transform:uppercase;letter-spacing:.15em;margin-bottom:8px; font-weight: bold;}
.active-panel .ap-topic{color:#fff;font-size:15px;font-weight:bold;margin-bottom:6px}
.active-panel .ap-meta{color:#888;font-size:12px;line-height:1.7}
.active-panel .ap-meta span{color:#ccc; font-weight: bold;}
#ap-timer{color:var(--accent);font-weight:bold;font-size:13px}

/* ── Tables ── */
.table-wrap {
  background: #0d0d0d;
  border: 1px solid #1a1a1a;
  border-radius: 6px;
  overflow: hidden;
  margin-bottom: 20px;
}
table{width:100%;border-collapse:collapse;}
th{text-align:left;color:#555;font-size:10px;text-transform:uppercase;letter-spacing:.1em;padding:10px 12px;background:#111;border-bottom:1px solid #1c1c1c}
td{padding:10px 12px;border-bottom:1px solid #131313;vertical-align:middle; color: #aaa;}
tr:last-child td { border-bottom: none; }
tr:hover td{background:#121212; color: #fff;}

/* ── Controls ── */
.controls{display:flex;gap:8px;flex-wrap:wrap;margin-bottom:20px}
.btn-group { display: flex; flex-direction: column; gap: 4px; }
.btn-desc { font-size: 9px; color: #444; padding-left: 2px; max-width: 140px; line-height: 1.2; }

/* ── Log event colors (static log + live feed share these classes) ── */
.lc-run    {color:var(--accent);font-weight:bold}
.lc-start  {color:#93c5fd}
.lc-done   {color:#6bcb77;font-weight:bold}
.lc-fail   {color:#ff6b6b;font-weight:bold}
.lc-search {color:#c4b5fd}
.lc-fetch  {color:#7dd3fc}
.lc-tool   {color:#4a4a5a}
.lc-note   {color:#4ecdc4}
.lc-memory {color:#a78bfa}
.lc-warn   {color:#ffd93d}
.lc-info   {color:#6b7280}

/* ── Log Colors & Container ── */
#log-container {
  background:#0c0c0c;
  padding:12px;
  border:1px solid #181818;
  border-radius:6px;
  max-height:400px;
  overflow-y:auto;
  scroll-behavior: smooth;
}
.log-entry { 
  font-size:11px; 
  padding:4px 0; 
  border-bottom:1px solid #141414; 
  display: flex;
  gap: 10px;
  align-items: flex-start;
}
.log-entry:last-child { border-bottom: none; }
.log-ts { color: var(--accent); opacity: 0.5; font-size: 10px; flex-shrink: 0; width: 60px; }
.log-msg { flex-grow: 1; word-break: break-all; }

/* ── Live feed ── */
.feed-wrap{
  position:relative;
  background:#0c0c0c;
  border:1px solid #1a1a1a;
  border-radius:4px;
  overflow:hidden;
}
.feed-wrap::before{
  content:'';
  position:absolute;
  top:0;left:-100%;
  width:60%;height:2px;
  background:var(--accent-grad);
  background-size:200% auto;
  animation:scanBar 2.8s ease-in-out infinite;
  z-index:2;pointer-events:none;
}
@keyframes scanBar{
  0%  {left:-60%}
  100%{left:110%}
}
#progress-feed{padding:10px;max-height:280px;overflow-y:auto;font-size:11px;line-height:1.5}
.pline{padding:1px 0;border-bottom:1px solid #0f0f0f;animation:fadeSlide .25s ease-out}
@keyframes fadeSlide{from{opacity:0;transform:translateY(-3px)}to{opacity:1;transform:none}}
.pline.lv-run   {color:var(--accent);font-weight:bold}
.pline.lv-done  {color:#6bcb77}
.pline.lv-fail  {color:#ff6b6b;font-weight:bold}
.pline.lv-tool  {color:#4a4a5a}
.pline.lv-warn  {color:#ffd93d}
.pline.lv-note  {color:#4ecdc4}
.pline.lv-info  {color:#7a7a8a}
.pline.lv-think {color:#888899;font-style:italic}
.pline.lv-cache {color:#a78bfa}
.pline.lv-feed  {color:#f472b6}

/* ── Nav ── */
nav{
  background:#0f0f0f;
  padding:7px 24px;
  border-bottom:1px solid #1c1c1c;
  display:flex;
  gap:0;
  align-items:center;
}
nav a{
  color:#666;font-size:12px;
  padding:4px 14px;
  border-right:1px solid #1a1a1a;
}
nav a:first-child{padding-left:0}
nav a.active,nav a:hover{color:#fff;text-decoration:none}
.live-dot{
  width:8px;height:8px;border-radius:50%;
  background:#252525;
  margin-left:auto;
  transition:background .4s;
}
.live-dot.on{background:#6bcb77;box-shadow:0 0 6px #6bcb7766;animation:dotPulse 1.4s ease-in-out infinite}
@keyframes dotPulse{0%,100%{opacity:1}50%{opacity:.3}}

/* ── Badges ── */
.b{display:inline-block;padding:1px 7px;border-radius:9px;font-size:10px;font-weight:bold;letter-spacing:.02em}
.b-high    {background:#280e0e;color:#ff6b6b}
.b-medium  {background:#1e1c08;color:#ffd93d}
.b-low     {background:#0c1c0c;color:#6bcb77}
.b-queued  {background:var(--accent-bg);color:var(--accent)}
.b-active  {background:#0c1c0c;color:#6bcb77}
.b-archived{background:#141414;color:#444}

/* ── Buttons ── */
form{display:inline}
button,input[type=submit]{
  background:#141414;color:var(--accent);
  border:1px solid var(--accent-border);
  padding:5px 12px;cursor:pointer;
  font-family:inherit;font-size:11px;border-radius:3px;
  transition:background .15s,border-color .15s;
}
button:hover,input[type=submit]:hover{background:var(--accent-bg);border-color:var(--accent-dim)}
.btn-sm{padding:2px 7px;font-size:10px}
.btn-danger{background:#180a0a;color:#ff6b6b;border-color:#360e0e}
.btn-danger:hover{background:#280c0c}
.btn-green{background:#0c1a0c;color:#6bcb77;border-color:#1a3e1a}
.btn-green:hover{background:#122212}
.btn-dim{background:#111;color:#666;border-color:#1e1e1e}
.btn-dim:hover{background:#171717;color:#999}

/* ── Inputs ── */
input[type=text],select,textarea{
  background:#111;color:#ccc;border:1px solid #222;
  padding:5px 9px;font-family:inherit;font-size:12px;border-radius:3px;
}
input[type=text]:focus,select:focus,textarea:focus{outline:none;border-color:var(--accent-dim)}
textarea{width:100%;min-height:300px;resize:vertical;line-height:1.5}
.row{display:flex;gap:10px;align-items:center;margin-bottom:9px;flex-wrap:wrap}
.row label{color:#666;min-width:65px;font-size:12px}
details summary{cursor:pointer;color:var(--accent);padding:4px 0;user-select:none;font-size:12px}

/* ── Misc ── */
pre{
  background:#0c0c0c;padding:12px;overflow-x:auto;border-radius:4px;
  border:1px solid #181818;white-space:pre-wrap;word-break:break-word;
  line-height:1.5;max-height:480px;overflow-y:auto;font-size:12px;
}
.tag{display:inline-block;background:#141414;color:#555;padding:1px 5px;border-radius:3px;font-size:10px;margin:1px}
.alert{padding:8px 13px;border-radius:4px;margin-bottom:12px;border:1px solid}
.alert-info {background:var(--accent-bg);border-color:var(--accent-border);color:var(--accent)}
.alert-ok   {background:#0c1a0c;border-color:#1c421c;color:#6bcb77}
.alert-warn {background:#1c1a08;border-color:#484620;color:#ffd93d}
.empty{color:#2e2e2e;font-style:italic;padding:12px 0;font-size:12px}
.meta-grid{
  background:#0f0f0f;border:1px solid #1c1c1c;padding:12px;border-radius:4px;
  margin-bottom:14px;display:grid;grid-template_columns:1fr 1fr;gap:6px 18px;
}
.meta-grid .lbl{color:#444}

/* ── Depth overview ── */
.depth-overview{
  background:#0d0d0d;border:1px solid #1a1a1a;border-radius:4px;
  padding:10px 14px;margin-bottom:14px;
}
.depth-row{display:flex;align-items:center;gap:8px;margin-bottom:4px;font-size:11px}
.depth-row .dlbl{color:#555;width:52px;flex-shrink:0}
.depth-bar-fill{height:6px;border-radius:3px;background:var(--accent-dim);min-width:2px;transition:width .4s}
.depth-bar-fill.deep-fill{background:#ffd93d}
.depth-row .dcount{color:#555;font-size:10px;min-width:20px;text-align:right}

/* ── Log colors ── */
.lc-run       {color:var(--accent)}
.lc-start     {color:#8ec8e8}
.lc-done      {color:#6bcb77}
.lc-fail      {color:#ff6b6b}
.lc-tool      {color:#353535}
.lc-note      {color:#4ecdc4}
.lc-info      {color:#7a7a7a}
.lc-warn      {color:#ffd93d}
</style>"""


# ── Time-based accent JS (runs immediately) ────────────────────────────────────

_ACCENT_JS = """<script>
(function(){
  var h=new Date().getHours()+new Date().getMinutes()/60;
  var keys=[[0,220],[6,185],[12,165],[18,270],[24,220]];
  var H=220;
  for(var i=0;i<keys.length-1;i++){
    if(h>=keys[i][0]&&h<keys[i+1][0]){
      var t=(h-keys[i][0])/(keys[i+1][0]-keys[i][0]);
      H=Math.round(keys[i][1]+t*(keys[i+1][1]-keys[i][1]));break;
    }
  }
  var r=document.documentElement.style;
  r.setProperty('--accent-h',H);
  r.setProperty('--accent','hsl('+H+',68%,62%)');
  r.setProperty('--accent-bright','hsl('+H+',80%,74%)');
  r.setProperty('--accent-dim','hsl('+H+',45%,38%)');
  r.setProperty('--accent-bg','hsl('+H+',28%,9%)');
  r.setProperty('--accent-border','hsl('+H+',35%,16%)');
  r.setProperty('--accent-grad',
    'linear-gradient(90deg,hsl('+H+',70%,58%),hsl('+(H+55)+',72%,70%),hsl('+H+',70%,58%))');
})();
</script>"""


# ── Helpers ────────────────────────────────────────────────────────────────────

def _badge(text: str) -> str:
    return f'<span class="b b-{_html.escape(text.lower())}">{_html.escape(text)}</span>'


def _depth_bar(depth: int) -> str:
    MAX = 6
    pips = "".join(
        f'<span class="depth-pip {"filled" if i < depth and depth < 3 else "deep" if i < depth else ""}" title="depth {depth}"></span>'
        for i in range(MAX)
    )
    lbl = f'<span style="color:#444;font-size:10px;margin-left:4px">{depth}</span>'
    return f'<span class="depth-bar">{pips}</span>{lbl}'


def _log_event_class(data: dict) -> str:
    ev  = data.get("event", "")
    lvl = data.get("level", "INFO")
    tool = data.get("tool", "")
    if lvl == "ERROR" or ev == "topic_failed":     return "lc-fail"
    if lvl == "WARN"  or ev == "warn":             return "lc-warn"
    if ev in ("run_start", "run_done"):            return "lc-run"
    if ev == "topic_start":                        return "lc-start"
    if ev == "topic_done":                         return "lc-done"
    if ev == "tool_call" and tool == "web_search": return "lc-search"
    if ev == "tool_call" and tool == "fetch_page": return "lc-fetch"
    if ev == "tool_call" and tool == "remember":   return "lc-note"
    if ev in ("tool_call", "tool_result"):         return "lc-tool"
    if ev == "note_written":                       return "lc-note"
    if ev == "memory_saved":                       return "lc-memory"
    return "lc-info"


def _hour_color(ts: str) -> str:
    """
    Map an HH:MM:SS timestamp to a hue interpolated across the 24-hour gradient.
    Keypoints: 0h=220, 6h=185, 12h=165, 18h=270, 24h=220
    Returns a CSS hsl() string at 65% saturation, 55% lightness.
    """
    try:
        parts = ts.split(":")
        hour = int(parts[0]) + (int(parts[1]) / 60 if len(parts) > 1 else 0)
    except Exception:
        hour = 12.0
    keys = [(0, 220), (6, 185), (12, 165), (18, 270), (24, 220)]
    for i in range(len(keys) - 1):
        h0, hue0 = keys[i]
        h1, hue1 = keys[i + 1]
        if h0 <= hour < h1:
            t = (hour - h0) / (h1 - h0)
            hue = round(hue0 + t * (hue1 - hue0))
            return f"hsl({hue},65%,55%)"
    return "hsl(220,65%,55%)"


def _format_log_line(raw: str) -> str:
    try:
        d   = json.loads(raw)
        ts  = (d.get("ts") or "")[-8:]
        ev  = d.get("event", "")
        cls = _log_event_class(d)
        topic = d.get("topic", d.get("slug", ""))
        tool  = d.get("tool", "")
        if ev == "run_start":
            msg = f">> run started  model={d.get('model','')}  queue={d.get('queue_size','')}"
        elif ev == "run_done":
            msg = f"== run done  ok={d.get('topics_completed',0)}  fail={d.get('topics_failed',0)}  elapsed={d.get('total_elapsed_s','')}s"
        elif ev == "topic_start":
            msg = f"-> [{d.get('position','')}/{d.get('of','')}] {topic}  {d.get('priority','')} / {d.get('type','')}"
        elif ev == "topic_done":
            msg = f"ok {topic}  {d.get('elapsed_s','')}s  src={d.get('sources',0)}  mem={d.get('memories',0)}  iter={d.get('iterations',0)}"
        elif ev == "topic_failed":
            msg = f"!! FAILED {topic}  {d.get('error','')}"
        elif ev == "tool_call":
            extra = d.get("query") or d.get("url") or d.get("key") or ""
            msg = f"   {tool}  {str(extra)[:80]}"
        elif ev == "tool_result":
            extra = f"  results={d.get('results_count','')}" if d.get("results_count") else ""
            msg = f"   {tool} done  {d.get('elapsed_ms','')}ms{extra}"
        elif ev == "note_written":
            msg = f"   note saved  {d.get('slug','')}  src={d.get('sources',0)}"
        elif ev == "memory_saved":
            msg = f"   memory #{d.get('memory_id','')} stored"
        elif d.get("level") == "WARN":
            extra = {k: v for k, v in d.items() if k not in ("ts","level","event")}
            msg = f"!! {ev}  " + "  ".join(f"{k}={v}" for k, v in extra.items())
        else:
            # unknown event — show key fields cleanly instead of raw JSON
            msg = f"   {ev}  {topic}" if (ev or topic) else raw[:120]

        # Hour-based timestamp color — interpolates through the same gradient as the accent
        ts_color = _hour_color(ts)
        return (
            f'<div class="log-entry {cls}">'
            f'<span class="log-ts" style="color:{ts_color}">{_html.escape(ts)}</span>'
            f'{_html.escape(msg)}</div>'
        )
    except Exception:
        cls = "lc-fail" if "ERROR" in raw or "FAIL" in raw.upper() else "lc-info"
        return f'<div class="log-entry {cls}">{_html.escape(raw[:180])}</div>'


def _nav(active: str = "") -> str:
    pages = [("/", "Dashboard"), ("/vault", "Vault"), ("/topics", "Topics"),
             ("/memory", "Memory"), ("/agents", "Agents"), ("/settings", "Settings")]
    links = "".join(
        f'<a href="{h}" class="{"active" if label.lower() == active else ""}">{label}</a>'
        for h, label in pages
    )
    dot_cls = "live-dot on" if _run_status["running"] else "live-dot"
    return (
        f'<div class="banner-wrap"><pre class="banner">{_BANNER}</pre></div>'
        f'<nav>{links}<span class="{dot_cls}" title="{"researching" if _run_status["running"] else "idle"}"></span></nav>'
    )


def _page(title: str, body: str, active: str = "") -> HTMLResponse:
    return HTMLResponse(
        f'<!DOCTYPE html><html><head>'
        f'<meta charset="utf-8"><meta name="viewport" content="width=device-width">'
        f'<title>{_html.escape(title)} — Phantom</title>'
        f'{_CSS}</head>'
        f'<body>{_ACCENT_JS}{_nav(active)}'
        f'<div class="container">{body}</div></body></html>'
    )


# ── API: stats ─────────────────────────────────────────────────────────────────

@app.get("/api/stats")
def api_stats():
    all_notes = _topics.list_topics()
    non_arch  = [n for n in all_notes if n.status != "archived"]
    depths    = [n.research_depth for n in non_arch]
    avg_depth = round(sum(depths) / len(depths), 1) if depths else 0
    # count forward links across all notes as a "connection" measure
    total_links = sum(len(n.forward_links) for n in all_notes)
    elapsed = round(_time.time() - _run_status["started_ts"], 0) if _run_status["running"] and _run_status["started_ts"] else 0
    return JSONResponse({
        "queued":        len([n for n in all_notes if n.status == "queued"]),
        "active_topics": len([n for n in all_notes if n.status == "active"]),
        "archived":      len([n for n in all_notes if n.status == "archived"]),
        "memories":      _memory.total_facts(),
        "sources":       _memory.total_sources(),
        "total_links":   total_links,
        "avg_depth":     avg_depth,
        "running":       _run_status["running"],
        "active_topic":  _run_status.get("active_topic", ""),
        "active_model":  _run_status.get("active_model", ""),
        "active_step":   _run_status.get("active_step", ""),
        "started_at":    _run_status.get("started_at", ""),
        "elapsed_s":     elapsed,
        "last":          _run_status.get("last", ""),
    })


# ── Dashboard ──────────────────────────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
def dashboard():
    all_notes  = _topics.list_topics()
    non_arch   = [n for n in all_notes if n.status != "archived"]
    queued_ct  = len([n for n in all_notes if n.status == "queued"])
    active_ct  = len([n for n in all_notes if n.status == "active"])
    arch_ct    = len([n for n in all_notes if n.status == "archived"])

    # ── Stat cards
    memories = _memory.total_facts()
    sources  = _memory.total_sources()
    total_links = sum(len(n.forward_links) for n in all_notes)
    depths   = [n.research_depth for n in non_arch]
    avg_depth = round(sum(depths) / len(depths), 1) if depths else 0

    stat_defs = [
        ("Topics",    "stat-topics",    len(non_arch)),
        ("Queued",    "stat-queued",    queued_ct),
        ("Memories",  "stat-memories",  memories),
        ("Sources",   "stat-sources",   sources),
        ("Links",     "stat-links",     total_links),
        ("Avg Depth", "stat-depth",     avg_depth),
    ]
    stats_html = "".join(
        f'<div class="stat"><div class="lbl">{lbl}</div><div class="val" id="{sid}">{val}</div></div>'
        for lbl, sid, val in stat_defs
    )

    # ── Active panel (shown when running)
    active_panel = ""
    if _run_status["running"]:
        t = _run_status.get("active_topic") or "initializing…"
        m = _run_status.get("active_model") or cfg.get("ollama.model", "?")
        s = _run_status.get("started_at", "")
        step = _run_status.get("active_step", "")
        elapsed = round(_time.time() - _run_status["started_ts"], 0) if _run_status["started_ts"] else 0
        active_panel = (
            '<div class="active-panel" id="active-panel">'
            '<div class="ap-label">Researching Now</div>'
            f'<div class="ap-topic">{_html.escape(t)}</div>'
            + (f'<div style="color:var(--accent);font-size:12px;margin-bottom:8px">{_html.escape(step)}</div>' if step else '') +
            '<div class="ap-meta">'
            f'model: <span>{_html.escape(m)}</span>'
            f'{" &nbsp;|&nbsp; started: <span>" + _html.escape(s) + "</span>" if s else ""}'
            f' &nbsp;|&nbsp; elapsed: <span id="ap-timer">{int(elapsed)}s</span>'
            '</div></div>'
        )

    # ── Control buttons
    run_label = "⏳ Running…" if _run_status["running"] else "▶ Run Research"
    run_dis   = "disabled" if _run_status["running"] else ""
    controls = (
        f'<div class="controls">'
        f'<div class="btn-group"><form method="post" action="/run"><button class="btn-green" {run_dis}>{run_label}</button></form>'
        f'<span class="btn-desc">Process the queue</span></div>'
        
        f'<div class="btn-group"><form method="post" action="/vault/rebuild"><button class="btn-dim">⟳ Rebuild Index</button></form>'
        f'<span class="btn-desc">Update backlinks and index</span></div>'
        
        f'<div class="btn-group"><form method="post" action="/context/reload"><button class="btn-dim">↺ Reload Context</button></form>'
        f'<span class="btn-desc">Pick up context.md edits</span></div>'
        
        f'<div class="btn-group"><a href="/topics?status=queued"><button class="btn-dim">Queue View</button></a>'
        f'<span class="btn-desc">See what is next</span></div>'

        f'<div class="btn-group"><button class="btn-dim" onclick="location.reload()">↻ Refresh Page</button>'
        f'<span class="btn-desc">Reload log &amp; stats</span></div>'
        f'</div>'
    )
    if _run_status.get("last"):
        last_cls = "alert-ok" if "complete" in _run_status["last"].lower() else "alert-warn"
        controls += f'<div class="alert {last_cls}" id="last-status">{_html.escape(_run_status["last"])}</div>'

    # ── Research overview (all non-archived, sorted by priority then depth)
    PRIO = {"high": 0, "medium": 1, "low": 2}
    sorted_topics = sorted(non_arch, key=lambda n: (PRIO.get(n.priority, 1), -n.research_depth, n.name))
    topic_rows = "".join(
        f'<tr>'
        f'<td><a href="/vault/{n.slug}">{_html.escape(n.name)}</a></td>'
        f'<td>{_badge(n.status)}</td>'
        f'<td>{_badge(n.priority)}</td>'
        f'<td style="color:#555">{n.type}</td>'
        f'<td>{_depth_bar(n.research_depth)}</td>'
        f'<td style="color:#444;font-size:11px">{str(n.last_researched or "never")[:10]}</td>'
        f'<td>'
        f'<form method="post" action="/topics/{n.slug}/research" style="display:inline">'
        f'<button class="btn-sm btn-green" title="Research now">▶</button></form>'
        f'</td>'
        f'</tr>'
        for n in sorted_topics
    ) or '<tr><td colspan="7" class="empty">No active topics — create one in Topics</td></tr>'

    queue_section = (
        f'<h2>Active Research Topics <span class="h2-count">{len(non_arch)}</span></h2>'
        f'<div class="table-wrap"><table><thead><tr>'
        f'<th>Topic</th><th>Status</th><th>Priority</th><th>Type</th>'
        f'<th>Depth</th><th>Last Research</th><th></th>'
        f'</tr></thead><tbody>{topic_rows}</tbody></table></div>'
    )

    # ── Depth distribution
    depth_counts = {}
    for n in non_arch:
        d = min(n.research_depth, 5)
        depth_counts[d] = depth_counts.get(d, 0) + 1
    max_count = max(depth_counts.values(), default=1)
    depth_labels = {0: "Cold", 1: "Verify", 2: "Cross", 3: "Deep", 4: "Power", 5: "Expert"}
    depth_rows_html = ""
    for lvl in range(6):
        cnt = depth_counts.get(lvl, 0)
        w   = max(4, round(cnt / max_count * 140)) if cnt else 0
        deep_cls = "deep-fill" if lvl >= 3 else ""
        depth_rows_html += (
            f'<div class="depth-row">'
            f'<span class="dlbl">{depth_labels[lvl]}</span>'
            f'<div class="depth-bar-fill {deep_cls}" style="width:{w}px"></div>'
            f'<span class="dcount">{cnt}</span>'
            f'</div>'
        )
    depth_overview = (
        f'<div class="depth-overview">'
        f'<div style="color:#555;font-size:9px;text-transform:uppercase;letter-spacing:.1em;margin-bottom:8px">'
        f'Knowledge Depth Distribution &nbsp;<span style="color:var(--accent)">avg {avg_depth}</span>'
        f'</div>'
        f'{depth_rows_html}'
        f'<div style="color:#333;font-size:10px;margin-top:6px">'
        f'{total_links} connections &nbsp;|&nbsp; {len(non_arch)} active topics</div>'
        f'</div>'
    )

    # ── Today's log
    log_html = '<span class="empty">No log entries yet</span>'
    log_path = f"logs/phantom-{date.today()}.log"
    if os.path.exists(log_path):
        try:
            with open(log_path, encoding="utf-8", errors="replace") as f:
                lines = [l.rstrip() for l in f if l.strip().startswith("{")]
            if lines:
                log_html = "".join(_format_log_line(l) for l in reversed(lines[-100:]))
        except Exception:
            pass
    log_section = (
        '<h2>Today\'s Log</h2>'
        f'<div id="log-container">{log_html}</div>'
    )

    # ── Live feed (right col)
    live_section = (
        '<h2>Live Progress</h2>'
        '<div class="feed-wrap">'
        '<div id="progress-feed"><span style="color:#282828;font-size:11px">Waiting for activity…</span></div>'
        '</div>'
    )

    # ── JS: SSE, stats refresh, timer
    js = """<script>
// ── Live feed & Log Tailing
(function(){
  var feed=document.getElementById('progress-feed');
  var logBox=document.getElementById('log-container');
  
  function cls(t){
    if(/^!!|FAILED|error/i.test(t))           return 'lc-fail';
    if(/^ok |run done/i.test(t))              return 'lc-done';
    if(/^>> run/i.test(t))                    return 'lc-run';
    if(/^== run done/i.test(t))               return 'lc-run';
    if(/^ *web_search/i.test(t))              return 'lc-search';
    if(/^ *fetch_page/i.test(t))              return 'lc-fetch';
    if(/^->/i.test(t))                        return 'lc-start';
    if(/note saved/i.test(t))                 return 'lc-note';
    if(/memory #/i.test(t))                   return 'lc-memory';
    if(/warn/i.test(t))                       return 'lc-warn';
    if(/ done [0-9]+ms/i.test(t))             return 'lc-tool';
    if(/^   [a-z_]+ /i.test(t))              return 'lc-tool';
    return 'lc-info';
  }

  function appendToLog(text) {
    if(!logBox) return;
    var d=document.createElement('div');
    d.className='log-entry ' + cls(text);
    var ts = new Date().toLocaleTimeString('en-GB', {hour12:false});
    d.innerHTML = '<span class="log-ts">'+ts+'</span><span class="log-msg">'+text+'</span>';
    logBox.insertBefore(d, logBox.firstChild);
    if(logBox.children.length > 200) logBox.removeChild(logBox.lastChild);
  }

  var es=new EventSource('/progress/stream');
  es.onmessage=function(e){
    if(e.data==='ping') return;
    var text; try{text=JSON.parse(e.data);}catch(x){text=e.data;}
    
    // Update live feed
    var d=document.createElement('div');
    d.className='pline '+cls(text);
    d.textContent=text;
    if(feed.firstChild&&feed.firstChild.textContent.indexOf('Waiting')!==-1)
      feed.innerHTML='';
    feed.insertBefore(d,feed.firstChild);
    if(feed.children.length>100) feed.removeChild(feed.lastChild);
    
    // Also append to the main log box
    appendToLog(text);
  };
})();

// ── Stats + active panel polling
function setTxt(id,v){var e=document.getElementById(id);if(e)e.textContent=v;}
setInterval(function(){
  fetch('/api/stats').then(function(r){return r.json();}).then(function(d){
    setTxt('stat-topics',   d.queued+(d.active_topics||0));
    setTxt('stat-queued',   d.queued);
    setTxt('stat-memories', d.memories);
    setTxt('stat-sources',  d.sources);
    setTxt('stat-links',    d.total_links||0);
    setTxt('stat-depth',    d.avg_depth||0);
    
    // nav dot + banner state
    var dot=document.querySelector('.live-dot');
    var banner=document.querySelector('.banner-wrap');
    if(dot){dot.className=d.running?'live-dot on':'live-dot';dot.title=d.running?'researching':'idle';}
    if(banner){ if(d.running) banner.classList.add('running'); else banner.classList.remove('running'); }
...    // active panel
    var ap=document.getElementById('active-panel');
    if(d.running){
      if(!ap){
        ap=document.createElement('div');ap.id='active-panel';ap.className='active-panel';
        var ctrl=document.querySelector('.controls');
        ctrl&&ctrl.parentNode.insertBefore(ap,ctrl.nextSibling);
      }
      var tname=d.active_topic||'initializing\u2026';
      var mname=d.active_model||'';
      var sat  =d.started_at||'';
      var step =d.active_step||'';
      ap.innerHTML='<div class="ap-label">Researching Now</div>'
        +'<div class="ap-topic">'+tname+'</div>'
        +(step?'<div style="color:var(--accent);font-size:12px;margin-bottom:8px">'+step+'</div>':'')
        +'<div class="ap-meta">'
        +(mname?'model: <span>'+mname+'</span> &nbsp;|&nbsp; ':'')
        +(sat?'started: <span>'+sat+'</span> &nbsp;|&nbsp; ':'')
        +'elapsed: <span id="ap-timer">'+Math.round(d.elapsed_s||0)+'s</span>'
        +'</div>';
    } else if(ap){
      ap.remove();
    }
    // last status
    if(d.last){
      var ls=document.getElementById('last-status');
      var cls2=d.last.toLowerCase().indexOf('complete')!==-1?'alert alert-ok':'alert alert-warn';
      if(ls){ls.textContent=d.last;ls.className=cls2;}
    }
  }).catch(function(){});
},5000);

// ── Active timer (counts up every second if running)
setInterval(function(){
  var t=document.getElementById('ap-timer');
  if(!t) return;
  var v=parseInt(t.textContent)||0;
  t.textContent=(v+1)+'s';
},1000);
</script>"""

    left  = f'{active_panel}{controls}{queue_section}'
    right = f'{live_section}{depth_overview}{log_section}'

    return _page("Dashboard", (
        f'<h1>Dashboard</h1>'
        f'<div class="stats">{stats_html}</div>'
        f'<div class="grid2"><div>{left}</div><div>{right}</div></div>'
        f'{js}'
    ), "dashboard")


@app.get("/settings", response_class=HTMLResponse)
def settings_page():
    # Load raw config and agents for editing
    try:
        with open("config.json", "r", encoding="utf-8") as f:
            config_raw = f.read()
    except Exception:
        config_raw = "{}"

    try:
        with open("agents.json", "r", encoding="utf-8") as f:
            agents_raw = f.read()
    except Exception:
        agents_raw = "{}"

    form = (
        f'<form method="post" action="/settings/save">'
        f'<h2>System Configuration (config.json)</h2>'
        f'<textarea name="config" style="height:300px;font-family:monospace">{_html.escape(config_raw)}</textarea>'
        f'<h2 style="margin-top:24px">Agent Roster (agents.json)</h2>'
        f'<textarea name="agents" style="height:300px;font-family:monospace">{_html.escape(agents_raw)}</textarea>'
        f'<div style="margin-top:20px">'
        f'<button type="submit" class="btn-green">✔ Save All Settings</button>'
        f'</div>'
        f'</form>'
    )
    return _page("Settings", f'<h1>System Settings</h1>{form}', "settings")


@app.post("/settings/save")
async def settings_save(request: Request):
    form = await request.form()
    config_raw = str(form.get("config", "{}"))
    agents_raw = str(form.get("agents", "{}"))

    # Validate JSON before saving
    try:
        json.loads(config_raw)
        json.loads(agents_raw)
    except json.JSONDecodeError as e:
        _run_status["last"] = f"JSON Error: {e}"
        return RedirectResponse("/settings", status_code=303)

    try:
        with open("config.json", "w", encoding="utf-8") as f:
            f.write(config_raw)
        with open("agents.json", "w", encoding="utf-8") as f:
            f.write(agents_raw)
        
        # Reload internal config
        cfg.reload()
        
        _run_status["last"] = "Settings saved and reloaded."
    except Exception as e:
        _run_status["last"] = f"Save error: {e}"

    return RedirectResponse("/settings", status_code=303)


# ── Vault list ─────────────────────────────────────────────────────────────────

@app.get("/vault", response_class=HTMLResponse)
def vault_list():
    notes = sorted(_topics.list_topics(), key=lambda n: n.name)
    rows  = "".join(
        f'<tr><td><a href="/vault/{n.slug}">{_html.escape(n.name)}</a></td>'
        f'<td>{_badge(n.status)}</td><td>{_badge(n.priority)}</td>'
        f'<td style="color:#555">{n.type}</td>'
        f'<td style="color:#484848">{str(n.last_researched or "never")[:10]}</td>'
        f'<td>{_depth_bar(n.research_depth)}</td>'
        f'<td style="color:var(--accent)">{n.research_runs or ""}</td>'
        f'<td style="color:#484848">{n.total_sources_fetched or ""}</td></tr>'
        for n in notes
    ) or '<tr><td colspan="8" class="empty">Vault is empty</td></tr>'

    body = (
        f'<h1>Vault <span style="color:#444;font-size:13px">({len(notes)} notes)</span></h1>'
        f'<table><thead><tr><th>Name</th><th>Status</th><th>Priority</th><th>Type</th>'
        f'<th>Last Researched</th><th>Depth</th><th>Runs</th><th>Sources</th></tr></thead>'
        f'<tbody>{rows}</tbody></table>'
    )
    return _page("Vault", body, "vault")


# ── Note detail ────────────────────────────────────────────────────────────────

@app.get("/vault/{slug}", response_class=HTMLResponse)
def vault_note(slug: str):
    note = _vault.read_note(slug)
    if not note:
        return _page("Not Found",
                     f'<div class="alert alert-warn">Note not found: {_html.escape(slug)}</div>',
                     "vault")

    tags  = "".join(f'<span class="tag">{_html.escape(t)}</span>' for t in note.tags) \
            or "<span style='color:#333'>none</span>"
    feeds = "".join(f'<span class="tag">{_html.escape(f)}</span>' for f in (note.feeds or [])) \
            or "<span style='color:#333'>none</span>"
    fwd   = ", ".join(
        f'<a href="/vault/{_vault.name_to_slug(l)}">{_html.escape(l)}</a>'
        for l in note.forward_links
    ) or "<span style='color:#333'>none</span>"

    meta = (
        '<div class="meta-grid">'
        f'<div><span class="lbl">Status</span> {_badge(note.status)}</div>'
        f'<div><span class="lbl">Priority</span> {_badge(note.priority)}</div>'
        f'<div><span class="lbl">Type</span> <span>{_html.escape(note.type)}</span></div>'
        f'<div><span class="lbl">Created</span> <span style="color:#888">{_html.escape(note.created)}</span></div>'
        f'<div><span class="lbl">Researched</span> <span style="color:#888">{_html.escape(str(note.last_researched or "never"))}</span></div>'
        f'<div><span class="lbl">Refresh</span> <span style="color:#888">every {note.refresh_interval_days}d</span></div>'
        f'<div><span class="lbl">Depth</span> {_depth_bar(note.research_depth)}</div>'
        f'<div><span class="lbl">Runs</span> <span style="color:var(--accent)">{note.research_runs}</span></div>'
        f'<div><span class="lbl">Sources</span> <span style="color:var(--accent)">{note.total_sources_fetched}</span></div>'
        f'<div style="grid-column:1/-1"><span class="lbl">Tags</span> {tags}</div>'
        f'<div style="grid-column:1/-1"><span class="lbl">Links to</span> {fwd}</div>'
        f'<div style="grid-column:1/-1"><span class="lbl">Feeds</span> {feeds}</div>'
        '</div>'
    )
    actions = (
        '<div style="display:flex;gap:6px;margin-bottom:14px;flex-wrap:wrap">'
        f'<form method="post" action="/topics/{note.slug}/research">'
        f'<button class="btn-green">▶ Research Now</button></form>'
        f'<a href="/vault/{note.slug}/edit"><button>✎ Edit Note</button></a>'
        f'<form method="post" action="/topics/{note.slug}/queue"><button>↺ Requeue</button></form>'
        f'<form method="post" action="/topics/{note.slug}/archive"><button class="btn-danger">Archive</button></form>'
        '<a href="/vault"><button class="btn-dim">← Back</button></a>'
        '</div>'
    )
    return _page(note.name, f'<h1>{_html.escape(note.name)}</h1>{actions}{meta}'
                             f'<h2>Note Content</h2><pre>{_html.escape(note.body or "")}</pre>', "vault")


@app.get("/vault/{slug}/edit", response_class=HTMLResponse)
def vault_note_edit(slug: str):
    note = _vault.read_note(slug)
    if not note:
        return RedirectResponse("/vault", status_code=303)

    # Metadata rows
    def _opt(val, current):
        return f'<option value="{val}" {"selected" if val==current else ""}>{val}</option>'

    status_opts = "".join(_opt(s, note.status) for s in ["queued", "active", "archived"])
    prio_opts   = "".join(_opt(p, note.priority) for p in ["high", "medium", "low"])
    type_opts   = "".join(_opt(t, note.type) for t in ["research", "tech", "person", "event", "concept"])

    form = (
        f'<form method="post" action="/vault/{slug}/save">'
        f'<div class="meta-grid">'
        f'<div><span class="lbl">Status</span> <select name="status">{status_opts}</select></div>'
        f'<div><span class="lbl">Priority</span> <select name="priority">{prio_opts}</select></div>'
        f'<div><span class="lbl">Type</span> <select name="type">{type_opts}</select></div>'
        f'<div><span class="lbl">Refresh</span> <input type="text" name="refresh" value="{note.refresh_interval_days}" style="width:50px"> days</div>'
        f'<div style="grid-column:1/-1"><span class="lbl">Tags</span> <input type="text" name="tags" value="{", ".join(note.tags)}" style="width:100%"></div>'
        f'<div style="grid-column:1/-1"><span class="lbl">Feeds</span> <input type="text" name="feeds" value="{", ".join(note.feeds)}" style="width:100%"></div>'
        f'</div>'
        f'<h2>Content</h2>'
        f'<textarea name="body">{_html.escape(note.body or "")}</textarea>'
        f'<div style="margin-top:20px;display:flex;gap:10px">'
        f'<button type="submit" class="btn-green">✔ Save Changes</button>'
        f'<a href="/vault/{slug}"><button type="button" class="btn-dim">Cancel</button></a>'
        f'</div>'
        f'</form>'
    )
    return _page(f"Edit {note.name}", f'<h1>Edit: {_html.escape(note.name)}</h1>{form}', "vault")


@app.post("/vault/{slug}/save")
async def vault_note_save(slug: str, request: Request):
    note = _vault.read_note(slug)
    if not note:
        return RedirectResponse("/vault", status_code=303)

    form = await request.form()
    note.status = str(form.get("status", "queued"))
    note.priority = str(form.get("priority", "medium"))
    note.type = str(form.get("type", "research"))
    note.refresh_interval_days = int(form.get("refresh", 7))
    note.tags = [t.strip() for t in str(form.get("tags", "")).split(",") if t.strip()]
    note.feeds = [f.strip() for f in str(form.get("feeds", "")).split(",") if f.strip()]
    note.body = str(form.get("body", ""))

    _vault.write_note(note)
    _vault.rebuild_backlinks()
    _run_status["last"] = f"Saved: {note.name}"

    return RedirectResponse(f"/vault/{slug}", status_code=303)


# ── Topics ─────────────────────────────────────────────────────────────────────

@app.get("/topics", response_class=HTMLResponse)
def topics_list(status: str = "all"):
    filters = " &nbsp;|&nbsp; ".join(
        f'<a href="/topics?status={s}" style="{"color:#fff" if s==status else ""}">{s}</a>'
        for s in ["all", "queued", "active", "archived"]
    )
    notes = _topics.list_topics(status=status if status != "all" else None)
    PRIO  = {"high": 0, "medium": 1, "low": 2}
    notes = sorted(notes, key=lambda n: (PRIO.get(n.priority, 1), n.name))

    rows = "".join(
        f'<tr><td><a href="/vault/{n.slug}">{_html.escape(n.name)}</a></td>'
        f'<td>{_badge(n.status)}</td><td>{_badge(n.priority)}</td>'
        f'<td style="color:#555">{n.type}</td>'
        f'<td>{"".join(f"<span class=tag>{_html.escape(t)}</span>" for t in n.tags)}</td>'
        f'<td style="color:#444;font-size:11px">{str(n.last_researched or "never")[:10]}</td>'
        f'<td style="color:#444">{n.refresh_interval_days}d</td>'
        f'<td style="white-space:nowrap">'
        f'<form method="post" action="/topics/{n.slug}/research" style="display:inline">'
        f'<button class="btn-sm btn-green" title="Research now">▶</button></form> '
        f'<form method="post" action="/topics/{n.slug}/queue" style="display:inline">'
        f'<button class="btn-sm" title="Requeue">↺</button></form> '
        f'<form method="post" action="/topics/{n.slug}/archive" style="display:inline">'
        f'<button class="btn-sm btn-danger" title="Archive">✕</button></form>'
        f'</td></tr>'
        for n in notes
    ) or '<tr><td colspan="8" class="empty">No topics</td></tr>'

    new_form = (
        '<details style="margin-top:16px"><summary>+ New Topic</summary>'
        '<form method="post" action="/topics/new" '
        'style="margin-top:10px;background:#0f0f0f;padding:14px;border:1px solid #1c1c1c;border-radius:4px">'
        '<div class="row"><label>Name</label><input type="text" name="name" required style="width:260px"></div>'
        '<div class="row"><label>Type</label>'
        '<select name="type"><option>research</option><option>tech</option><option>person</option>'
        '<option>event</option><option>concept</option></select>'
        '<label style="margin-left:14px">Priority</label>'
        '<select name="priority"><option>medium</option><option>high</option><option>low</option></select></div>'
        '<div class="row"><label>Tags</label><input type="text" name="tags" placeholder="comma separated"></div>'
        '<div class="row"><input type="submit" value="Create Topic"></div>'
        '</form></details>'
    )
    return _page("Topics", (
        f'<h1>Topics <span style="color:#444;font-size:13px">({len(notes)})</span></h1>'
        f'<div style="margin-bottom:10px;color:#555;font-size:11px">Filter: {filters}</div>'
        f'<table><thead><tr><th>Name</th><th>Status</th><th>Priority</th><th>Type</th>'
        f'<th>Tags</th><th>Last Research</th><th>Refresh</th><th></th></tr></thead>'
        f'<tbody>{rows}</tbody></table>{new_form}'
    ), "topics")


@app.post("/topics/new")
async def new_topic(request: Request):
    form  = await request.form()
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


# ── Memory ─────────────────────────────────────────────────────────────────────

@app.get("/memory", response_class=HTMLResponse)
def memory_page(q: str = ""):
    stats = (
        '<div class="stats">'
        f'<div class="stat"><div class="lbl">Total Facts</div><div class="val">{_memory.total_facts()}</div></div>'
        f'<div class="stat"><div class="lbl">Sources</div><div class="val">{_memory.total_sources()}</div></div>'
        '</div>'
    )
    search = (
        f'<form method="get" action="/memory" style="display:flex;gap:8px;margin-bottom:16px">'
        f'<input type="text" name="q" value="{_html.escape(q)}" placeholder="Search memories…" style="width:340px">'
        f'<input type="submit" value="Search"></form>'
    )
    if q:
        results = _memory.hybrid_search(q, limit=20)
        rows = "".join(
            f'<tr><td style="color:#444">{r["id"]}</td>'
            f'<td>{_html.escape(r["content"][:300])}'
            f'{"<span style=color:#444;font-size:10px> [sim:" + str(round(r.get("semantic_score",0),2)) + "]</span>" if r.get("semantic_score") else ""}'
            f'</td><td><span class="tag">{_html.escape(r.get("tags",""))}</span></td>'
            f'<td style="color:#444;font-size:11px">{(r["created_at"] or "")[:10]}</td></tr>'
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
            f'<tr><td style="color:#444">{r["id"]}</td>'
            f'<td>{_html.escape(r["content"][:300])}</td>'
            f'<td><span class="tag">{_html.escape(r.get("tags",""))}</span></td>'
            f'<td style="color:#444;font-size:11px">{(r["created_at"] or "")[:10]}</td></tr>'
            for r in recent
        ) or '<tr><td colspan="4" class="empty">No memories yet</td></tr>'
        results_html = (
            '<h2>Recent Memories</h2>'
            '<table><thead><tr><th>ID</th><th>Content</th><th>Tags</th><th>Date</th></tr></thead>'
            f'<tbody>{rows}</tbody></table>'
        )
    return _page("Memory", f'<h1>Memory</h1>{stats}{search}{results_html}', "memory")


# ── Agents ─────────────────────────────────────────────────────────────────────

@app.get("/agents", response_class=HTMLResponse)
def agents_page():
    try:
        from agents import AgentRoster
        roster    = AgentRoster()
        available = roster.list_available()
    except Exception as e:
        return _page("Agents",
                     f'<div class="alert alert-warn">Could not load roster: {_html.escape(str(e))}</div>',
                     "agents")

    rows = "".join(
        f'<tr>'
        f'<td><strong>{_html.escape(a["model"])}</strong>'
        f'{"<span style=color:#444> (" + _html.escape(a.get("nickname","")) + ")</span>" if a.get("nickname") else ""}'
        f'</td>'
        f'<td style="color:{"#6bcb77" if a.get("loaded") else "var(--accent)" if a.get("available") else "#ff6b6b"}">'
        f'{"HOT" if a.get("loaded") else "online" if a.get("available") else "offline"}</td>'
        f'<td>{_html.escape(", ".join(a.get("assigned_types",[]) or []) or "—")}</td>'
        f'<td>{_html.escape(", ".join(a.get("capabilities",[]) or []) or "—")}</td>'
        f'<td style="color:#555">{_html.escape(a.get("description",""))}</td>'
        f'</tr>'
        for a in available
    ) or '<tr><td colspan="5" class="empty">No models found — is Ollama running?</td></tr>'

    default = cfg.get("ollama.model", "unknown")
    return _page("Agents", (
        f'<h1>Agent Roster</h1>'
        f'<div class="alert alert-info">Default model: <strong>{_html.escape(default)}</strong></div>'
        f'<p style="color:#444;margin-bottom:14px;font-size:11px">Use <code>/agents assign</code> in the CLI to modify assignments.</p>'
        f'<table><thead><tr><th>Model</th><th>Status</th><th>Types</th><th>Capabilities</th><th>Description</th></tr></thead>'
        f'<tbody>{rows}</tbody></table>'
    ), "agents")


# ── Vault actions ──────────────────────────────────────────────────────────────

@app.post("/vault/rebuild")
def vault_rebuild():
    try:
        _vault.rebuild_index()
        _vault.rebuild_backlinks()
        _run_status["last"] = "Vault index and backlinks rebuilt."
    except Exception as e:
        _run_status["last"] = f"Rebuild error: {e}"
    return RedirectResponse("/", status_code=303)


@app.post("/context/reload")
def context_reload():
    try:
        from context import reload_context
        reload_context()
        _run_status["last"] = "Context reloaded from disk."
    except Exception as e:
        _run_status["last"] = f"Context reload error: {e}"
    return RedirectResponse("/", status_code=303)


# ── Force-research ─────────────────────────────────────────────────────────────

@app.post("/topics/{slug}/research")
def force_research(slug: str):
    note = _vault.read_note(slug)
    if not note:
        return RedirectResponse(f"/vault/{slug}", status_code=303)
    _topics.update_status(slug, "queued")

    def _do():
        _run_status["running"]      = True
        _run_status["active_topic"] = note.name
        _run_status["active_model"] = cfg.get("ollama.model", "")
        _run_status["started_at"]   = datetime.now().strftime("%H:%M:%S")
        _run_status["started_ts"]   = _time.time()
        try:
            from scheduler import ResearchScheduler
            from agents import AgentRoster
            mem    = MemoryStore(cfg.get("memory.db_path", "data/memory.db"))
            vault  = VaultManager(cfg.get("vault.path", "vault"))
            tpcs   = TopicManager(vault)
            roster = AgentRoster()

            def _single():
                n = vault.read_note(slug)
                return [n] if n else []
            tpcs.get_research_candidates = _single

            scheduler = ResearchScheduler(mem, vault, tpcs, roster=roster, max_topics=1)
            _hook_scheduler_log(scheduler)
            result = scheduler.run()
            _run_status["last"] = f"Force-research complete: {note.name}"
            mem.close()
        except Exception as e:
            _run_status["last"] = f"Force-research error: {e}"
        finally:
            _run_status["running"]      = False
            _run_status["active_topic"] = ""
            _run_status["active_model"] = ""
            _run_status["active_step"]  = ""
            _run_status["started_ts"]   = 0.0

    threading.Thread(target=_do, daemon=True).start()
    return RedirectResponse(f"/vault/{slug}", status_code=303)


# ── SSE live stream ────────────────────────────────────────────────────────────

@app.get("/progress/stream")
def progress_stream():
    q: queue.Queue = queue.Queue(maxsize=200)
    with _sse_lock:
        _sse_subscribers.append(q)

    def _generate():
        try:
            while True:
                try:
                    msg = q.get(timeout=25)
                    yield f"data: {json.dumps(msg)}\n\n"
                except queue.Empty:
                    yield "data: ping\n\n"
        finally:
            with _sse_lock:
                if q in _sse_subscribers:
                    _sse_subscribers.remove(q)

    return StreamingResponse(
        _generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# ── Schedule run ───────────────────────────────────────────────────────────────

@app.post("/run")
def trigger_run():
    if _run_status["running"]:
        return RedirectResponse("/", status_code=303)

    def _do():
        _run_status["running"]    = True
        _run_status["started_at"] = datetime.now().strftime("%H:%M:%S")
        _run_status["started_ts"] = _time.time()
        try:
            from scheduler import ResearchScheduler
            from agents import AgentRoster
            mem    = MemoryStore(cfg.get("memory.db_path", "data/memory.db"))
            vault  = VaultManager(cfg.get("vault.path", "vault"))
            topics = TopicManager(vault)
            roster = AgentRoster()

            # Fall back to loop-style weighted pick when queue/stale is empty
            _orig = topics.get_research_candidates
            def _with_fallback():
                cands = _orig()
                if not cands:
                    loop = topics.get_loop_candidates()
                    if loop:
                        batch, picked, seen = cfg.get("schedule.loop_batch_size", 3), [], set()
                        for _ in range(batch):
                            eligible = [n for n in loop if n.slug not in seen]
                            if not eligible:
                                break
                            note = topics.weighted_pick(eligible)
                            if note:
                                picked.append(note)
                                seen.add(note.slug)
                        return picked
                return cands
            topics.get_research_candidates = _with_fallback

            scheduler = ResearchScheduler(mem, vault, topics, roster=roster)
            _hook_scheduler_log(scheduler)
            result = scheduler.run()
            _run_status["last"] = (
                f"Run complete: {result.topics_succeeded} succeeded, {result.topics_failed} failed."
            )
            mem.close()
        except Exception as e:
            _run_status["last"] = f"Run error: {e}"
        finally:
            _run_status["running"]      = False
            _run_status["active_topic"] = ""
            _run_status["active_model"] = ""
            _run_status["active_step"]  = ""
            _run_status["started_ts"]   = 0.0

    threading.Thread(target=_do, daemon=True).start()
    return RedirectResponse("/", status_code=303)


# ── Entry ──────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("\n  Phantom Web UI  →  http://127.0.0.1:7777\n")
    uvicorn.run(app, host="127.0.0.1", port=7777, log_level="warning")
