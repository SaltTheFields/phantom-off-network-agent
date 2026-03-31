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
  background:#060608;
  border-bottom:1px solid #1a1a2a;
  padding:14px 24px 10px;
  overflow:hidden;
  position:relative;
}
/* scan-line sweep */
.banner-wrap::before {
  content:'';
  position:absolute;
  top:-100%; left:0; right:0;
  height:200%;
  background:repeating-linear-gradient(
    0deg,
    transparent,
    transparent 3px,
    rgba(100,200,255,0.018) 3px,
    rgba(100,200,255,0.018) 4px
  );
  pointer-events:none;
  animation:scanDown 12s linear infinite;
}
/* running: radial pulse + faster scan */
.banner-wrap.running::after {
  content:'';
  position:absolute;
  top:0; left:0; right:0; bottom:0;
  background:radial-gradient(ellipse at 50% 120%, hsl(200,80%,20%) 0%, transparent 65%);
  opacity:0;
  pointer-events:none;
  animation:pulseBg 3s ease-in-out infinite;
}
.banner-wrap.running::before { animation-duration:4s; }
@keyframes scanDown  { from{transform:translateY(0)} to{transform:translateY(50%)} }
@keyframes pulseBg   { 0%,100%{opacity:0} 50%{opacity:0.55} }

.banner{
  display:inline-block;
  font-size:13px;
  line-height:1.3;
  letter-spacing:.02em;
  white-space:pre;
  font-weight:bold;
  background:linear-gradient(90deg,
    #7dd3fc 0%,
    #a78bfa 18%,
    #f472b6 34%,
    #fb923c 50%,
    #facc15 66%,
    #4ade80 82%,
    #7dd3fc 100%
  );
  background-size:300% auto;
  -webkit-background-clip:text;
  -webkit-text-fill-color:transparent;
  background-clip:text;
  animation:bannerFlow 10s linear infinite;
  user-select:none;
  position:relative;
  z-index:1;
}
.banner-wrap.running .banner {
  animation:bannerFlow 4s linear infinite, glowPulse 1.8s ease-in-out infinite alternate;
}
@keyframes bannerFlow  { 0%{background-position:0% center} 100%{background-position:300% center} }
@keyframes glowPulse   { from{filter:drop-shadow(0 0 3px #7dd3fc88) drop-shadow(0 0 8px #a78bfa44)}
                           to{filter:drop-shadow(0 0 10px #7dd3fccc) drop-shadow(0 0 22px #a78bfa88)} }

.banner-sub{
  font-size:10px;
  margin-top:3px;
  padding-left:2px;
  letter-spacing:.25em;
  text-transform:uppercase;
  position:relative;z-index:1;
  background:linear-gradient(90deg,#a78bfa,#7dd3fc,#4ade80,#a78bfa);
  background-size:250% auto;
  -webkit-background-clip:text;
  -webkit-text-fill-color:transparent;
  background-clip:text;
  animation:bannerFlow 8s linear infinite reverse;
}
/* auto-refresh countdown */
#refresh-bar{
  position:absolute;bottom:0;left:0;
  height:2px;
  background:linear-gradient(90deg,#7dd3fc,#a78bfa,#4ade80);
  transition:width 1s linear;
  z-index:2;
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

/* ── Rendered markdown ── */
.md-body{line-height:1.75;color:#c0c0c0;font-size:13px}
.md-body h1{font-size:17px;color:#fff;margin:20px 0 10px;border-left:3px solid var(--accent);padding-left:10px;letter-spacing:.03em}
.md-body h2{font-size:12px;color:var(--accent);text-transform:uppercase;letter-spacing:.15em;margin:20px 0 8px;padding-bottom:4px;border-bottom:1px solid var(--accent-border)}
.md-body h3{font-size:13px;color:#aaa;margin:14px 0 6px;letter-spacing:.04em}
.md-body p{margin:8px 0}
.md-body ul,.md-body ol{padding-left:22px;margin:8px 0}
.md-body li{margin:4px 0;color:#b0b0b0}
.md-body blockquote{border-left:3px solid var(--accent-dim);padding:6px 14px;color:#777;margin:10px 0;font-style:italic}
.md-body code{background:#141414;color:#c4b5fd;padding:1px 5px;border-radius:3px;font-size:11px}
.md-body pre{background:#0c0c0c;border:1px solid #181818;padding:12px;border-radius:4px;overflow-x:auto;margin:10px 0}
.md-body pre code{background:none;padding:0;color:#a8c0b0;font-size:11px}
.md-body a{color:var(--accent)}
.md-body a:hover{color:var(--accent-bright)}
.md-body hr{border:none;border-top:1px solid #1e1e1e;margin:18px 0}
.md-body strong{color:#ddd;font-weight:bold}
.md-body em{color:#aaa;font-style:italic}
.wikilink{color:var(--accent-bright) !important;border-bottom:1px dashed var(--accent-dim)}
.wikilink-ghost{color:#446677 !important;border-bottom:1px dashed #334455;font-style:italic}
.callout{border-radius:4px;padding:10px 16px;margin:12px 0;border-left:4px solid;font-size:12px}
.callout-warning{background:#1c1a08;border-color:#ffd93d;color:#ffd93d}
.callout-note   {background:var(--accent-bg);border-color:var(--accent);color:var(--accent)}
.callout-info   {background:var(--accent-bg);border-color:var(--accent);color:var(--accent)}
.callout-tip    {background:#0c1a0c;border-color:#6bcb77;color:#6bcb77}
.callout-danger {background:#180a0a;border-color:#ff6b6b;color:#ff6b6b}
.callout-icon   {margin-right:6px;font-style:normal}

/* ── Graph page ── */
#graph-canvas{display:block;background:#0a0a0a;border:1px solid #1a1a1a;border-radius:6px;cursor:grab}
#graph-canvas:active{cursor:grabbing}
.graph-legend{display:flex;gap:14px;flex-wrap:wrap;margin-bottom:12px;font-size:11px}
.legend-item{display:flex;align-items:center;gap:5px;color:#666}
.legend-dot{width:10px;height:10px;border-radius:50%;flex-shrink:0}
#graph-tooltip{
  position:fixed;pointer-events:none;display:none;
  background:#111;border:1px solid var(--accent-border);
  border-radius:4px;padding:8px 12px;font-size:11px;
  color:#ccc;z-index:999;max-width:220px;line-height:1.5;
}
#graph-info{
  background:#0f0f0f;border:1px solid #1c1c1c;border-radius:4px;
  padding:12px 16px;margin-top:12px;min-height:50px;font-size:12px;color:#888;
}
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


_INLINE_RE = None

def _inline(text: str) -> str:
    """Render inline markdown: WikiLinks, md links, code, bold, italic. HTML-safe."""
    import re
    global _INLINE_RE
    if _INLINE_RE is None:
        _INLINE_RE = re.compile(
            r'(?P<wiki>\[\[(?P<wname>[^\]\|]+)(?:\|[^\]]*)?\]\])'
            r'|(?P<mdlink>\[(?P<ltext>[^\]]+)\]\((?P<lurl>[^)]+)\))'
            r'|(?P<code>`(?P<ctext>[^`]+)`)'
            r'|(?P<bold>\*\*(?P<btext>[^*]+)\*\*)'
            r'|(?P<italic>\*(?P<itext>[^*\n]+)\*)'
        )
    result = []
    last = 0
    for m in _INLINE_RE.finditer(text):
        result.append(_html.escape(text[last:m.start()]))
        last = m.end()
        if m.group('wiki'):
            name = m.group('wname').strip()
            slug = _vault.name_to_slug(name)
            # Check if note actually exists; ghost links get a dimmer style
            exists = slug in {n.slug for n in _topics.list_topics()}
            cls = 'wikilink' if exists else 'wikilink wikilink-ghost'
            title = '' if exists else ' title="Not yet researched"'
            result.append(f'<a href="/vault/{slug}" class="{cls}"{title}>[[{_html.escape(name)}]]</a>')
        elif m.group('mdlink'):
            result.append(f'<a href="{_html.escape(m.group("lurl"))}" target="_blank" rel="noopener">{_html.escape(m.group("ltext"))}</a>')
        elif m.group('code'):
            result.append(f'<code>{_html.escape(m.group("ctext"))}</code>')
        elif m.group('bold'):
            result.append(f'<strong>{_html.escape(m.group("btext"))}</strong>')
        elif m.group('italic'):
            result.append(f'<em>{_html.escape(m.group("itext"))}</em>')
    result.append(_html.escape(text[last:]))
    return ''.join(result)


def _render_markdown(text: str) -> str:
    """Convert a vault note markdown body to safe HTML."""
    import re
    if not text or not text.strip():
        return '<p class="empty">No content yet.</p>'

    _CALLOUT_ICON = {'warning': '⚠', 'note': 'ℹ', 'info': 'ℹ', 'tip': '💡', 'danger': '☢'}
    lines  = text.splitlines()
    out    = []
    i      = 0
    in_ul  = False
    in_ol  = False

    def close_list():
        nonlocal in_ul, in_ol
        if in_ul: out.append('</ul>'); in_ul = False
        if in_ol: out.append('</ol>'); in_ol = False

    while i < len(lines):
        line = lines[i]

        # ── Fenced code block ──────────────────────────────────────────────────
        if line.strip().startswith('```'):
            close_list()
            lang  = _html.escape(line.strip()[3:].strip())
            code  = []
            i += 1
            while i < len(lines) and not lines[i].strip().startswith('```'):
                code.append(lines[i])
                i += 1
            cls = f' class="lang-{lang}"' if lang else ''
            out.append(f'<pre><code{cls}>{_html.escape(chr(10).join(code))}</code></pre>')

        # ── Headings ──────────────────────────────────────────────────────────
        elif re.match(r'^#{4,6} ', line):
            close_list()
            txt = re.sub(r'^#{4,6} ', '', line)
            out.append(f'<h3>{_inline(txt)}</h3>')
        elif line.startswith('### '):
            close_list()
            out.append(f'<h3>{_inline(line[4:])}</h3>')
        elif line.startswith('## '):
            close_list()
            out.append(f'<h2>{_inline(line[3:])}</h2>')
        elif line.startswith('# '):
            close_list()
            out.append(f'<h1>{_inline(line[2:])}</h1>')

        # ── HR ────────────────────────────────────────────────────────────────
        elif re.match(r'^[-*_]{3,}\s*$', line):
            close_list()
            out.append('<hr>')

        # ── Callouts  > [!type] ───────────────────────────────────────────────
        elif re.match(r'^> \[!', line):
            close_list()
            m = re.match(r'^> \[!(\w+)\](.*)', line)
            ctype = m.group(1).lower() if m else 'note'
            rest  = (m.group(2) or '').strip() if m else ''
            body_lines = [rest] if rest else []
            i += 1
            while i < len(lines) and lines[i].startswith('> '):
                body_lines.append(lines[i][2:])
                i += 1
            icon = _CALLOUT_ICON.get(ctype, '▸')
            out.append(
                f'<div class="callout callout-{_html.escape(ctype)}">'
                f'<span class="callout-icon">{icon}</span>'
                f'{_inline(" ".join(body_lines))}</div>'
            )
            continue

        # ── Blockquote ────────────────────────────────────────────────────────
        elif line.startswith('> '):
            close_list()
            out.append(f'<blockquote>{_inline(line[2:])}</blockquote>')

        # ── Bullet list ───────────────────────────────────────────────────────
        elif re.match(r'^[-*] ', line):
            if in_ol: out.append('</ol>'); in_ol = False
            if not in_ul: out.append('<ul>'); in_ul = True
            out.append(f'<li>{_inline(line[2:])}</li>')

        # ── Ordered list ──────────────────────────────────────────────────────
        elif re.match(r'^\d+\. ', line):
            if in_ul: out.append('</ul>'); in_ul = False
            if not in_ol: out.append('<ol>'); in_ol = True
            out.append(f'<li>{_inline(re.sub(r"^\d+\. ", "", line))}</li>')

        # ── Empty line ────────────────────────────────────────────────────────
        elif line.strip() == '':
            close_list()

        # ── Paragraph ─────────────────────────────────────────────────────────
        else:
            close_list()
            out.append(f'<p>{_inline(line)}</p>')

        i += 1

    close_list()
    return '\n'.join(out)


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
            pos = d.get('position', '')
            of  = d.get('of', 0)
            of_str = f"pool:{of}" if of else "loop"
            msg = f"-> [#{pos}/{of_str}] {topic}  {d.get('priority','')} / {d.get('type','')}"
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
    pages = [("/", "Dashboard"), ("/vault", "Vault"), ("/graph", "Graph"),
             ("/topics", "Topics"), ("/sources", "Sources"), ("/search", "Search"),
             ("/memory", "Memory"), ("/agents", "Agents"), ("/settings", "Settings")]
    links = "".join(
        f'<a href="{h}" class="{"active" if label.lower() == active else ""}">{label}</a>'
        for h, label in pages
    )
    dot_cls = "live-dot on" if _run_status["running"] else "live-dot"
    return (
        f'<div class="banner-wrap" id="banner-wrap"><pre class="banner">{_BANNER}</pre>'
        f'<div class="banner-sub">off-network-agent</div>'
        f'<div id="refresh-bar" style="width:100%"></div></div>'
        f'<nav>{links}<span class="{dot_cls}" title="{"researching" if _run_status["running"] else "idle"}"></span></nav>'
    )


_TAB_JS = """<script>
(function(){
  /* ── Animated favicon ── */
  var fc=document.createElement('canvas');
  fc.width=fc.height=32;
  var fx=fc.getContext('2d');
  var _fhue=0;
  var _flink=document.querySelector('link[rel~="icon"]');
  if(!_flink){_flink=document.createElement('link');_flink.rel='icon';document.head.appendChild(_flink);}

  function drawFavicon(){
    fx.clearRect(0,0,32,32);
    /* outer glow ring */
    var grad=fx.createRadialGradient(16,16,4,16,16,15);
    grad.addColorStop(0,'hsla('+_fhue+',90%,65%,0.9)');
    grad.addColorStop(0.6,'hsla('+((_fhue+60)%360)+',80%,50%,0.5)');
    grad.addColorStop(1,'hsla('+((_fhue+120)%360)+',70%,40%,0)');
    fx.fillStyle=grad;
    fx.beginPath();fx.arc(16,16,15,0,Math.PI*2);fx.fill();
    /* inner diamond ◈ */
    fx.save();
    fx.translate(16,16);
    fx.rotate(_fhue*Math.PI/180);
    fx.fillStyle='hsla('+((_fhue+180)%360)+',100%,75%,1)';
    fx.beginPath();
    fx.moveTo(0,-9);fx.lineTo(9,0);fx.lineTo(0,9);fx.lineTo(-9,0);fx.closePath();
    fx.fill();
    /* inner cutout */
    fx.fillStyle='#0b0b0b';
    fx.beginPath();
    fx.moveTo(0,-4);fx.lineTo(4,0);fx.lineTo(0,4);fx.lineTo(-4,0);fx.closePath();
    fx.fill();
    fx.restore();
    _flink.href=fc.toDataURL('image/png');
    _fhue=(_fhue+1.8)%360;
  }
  setInterval(drawFavicon,60);
  drawFavicon();

  /* ── theme-color pulse ── */
  var _tmeta=document.querySelector('meta[name="theme-color"]');
  if(!_tmeta){_tmeta=document.createElement('meta');_tmeta.name='theme-color';document.head.appendChild(_tmeta);}
  var _thue=200;
  setInterval(function(){
    _thue=(_thue+0.4)%360;
    _tmeta.content='hsl('+_thue+',30%,8%)';
  },50);

  /* ── Dynamic tab title ── */
  var _baseTitle=document.title;
  var _titleFrames=['◈','◇','◈','◆'];
  var _tfi=0;
  setInterval(function(){
    fetch('/api/stats').then(function(r){return r.json();}).then(function(d){
      _tfi=(_tfi+1)%_titleFrames.length;
      var icon=_titleFrames[_tfi];
      if(d.running && d.active_topic){
        document.title=icon+' '+d.active_topic+' — Phantom';
      } else {
        document.title=icon+' '+_baseTitle;
      }
    }).catch(function(){});
  },2000);
})();
</script>"""

def _page(title: str, body: str, active: str = "") -> HTMLResponse:
    return HTMLResponse(
        f'<!DOCTYPE html><html><head>'
        f'<meta charset="utf-8"><meta name="viewport" content="width=device-width">'
        f'<meta name="theme-color" content="#0b0b10">'
        f'<title>{_html.escape(title)} — Phantom</title>'
        f'{_CSS}</head>'
        f'<body>{_ACCENT_JS}{_TAB_JS}{_nav(active)}'
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
    # Cap elapsed at 6h — anything longer means the run_done event was missed
    _MAX_ELAPSED = 6 * 3600
    if _run_status["running"] and _run_status["started_ts"]:
        elapsed = round(_time.time() - _run_status["started_ts"], 0)
        if elapsed > _MAX_ELAPSED:
            _run_status["running"] = False
            _run_status["started_ts"] = 0.0
            elapsed = 0
    else:
        elapsed = 0
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

    # ── Research overview — currently-researching topic pinned first, then priority+depth
    PRIO = {"high": 0, "medium": 1, "low": 2}
    active_slug = (_run_status.get("active_topic") or "").lower().replace(" ", "-")
    # try to match by name→slug if the stored value is a display name
    if active_slug and not any(n.slug == active_slug for n in non_arch):
        from vault import VaultManager as _VM
        active_slug = _vault.name_to_slug(_run_status.get("active_topic", ""))

    def _topic_sort_key(n):
        is_active = (n.slug == active_slug and _run_status["running"])
        return (0 if is_active else 1, PRIO.get(n.priority, 1), -n.research_depth, n.name)

    sorted_topics = sorted(non_arch, key=_topic_sort_key)

    def _topic_row(n):
        is_active = n.slug == active_slug and _run_status["running"]
        row_style = (
            'background:linear-gradient(90deg,#0a1a0a,#0b1520);'
            'border-left:3px solid #4ade80;'
        ) if is_active else ''
        indicator = (
            '<span style="display:inline-block;width:7px;height:7px;border-radius:50%;'
            'background:#4ade80;box-shadow:0 0 6px #4ade80;margin-right:6px;'
            'animation:glowPulse 1.2s ease-in-out infinite alternate"></span>'
        ) if is_active else ''
        return (
            f'<tr style="{row_style}">'
            f'<td><a href="/vault/{n.slug}">{indicator}{_html.escape(n.name)}</a></td>'
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
        )

    topic_rows = "".join(_topic_row(n) for n in sorted_topics) \
        or '<tr><td colspan="7" class="empty">No active topics — create one in Topics</td></tr>'

    # Archived rows (hidden by default, revealed by checkbox)
    arch_notes = sorted([n for n in all_notes if n.status == "archived"],
                        key=lambda n: n.name)
    arch_rows = "".join(
        f'<tr style="opacity:0.45">'
        f'<td><a href="/vault/{n.slug}">{_html.escape(n.name)}</a></td>'
        f'<td>{_badge(n.status)}</td>'
        f'<td>{_badge(n.priority)}</td>'
        f'<td style="color:#555">{n.type}</td>'
        f'<td>{_depth_bar(n.research_depth)}</td>'
        f'<td style="color:#444;font-size:11px">{str(n.last_researched or "never")[:10]}</td>'
        f'<td>'
        f'<form method="post" action="/topics/{n.slug}/queue" style="display:inline">'
        f'<button class="btn-sm" title="Unarchive">↺</button></form>'
        f'</td>'
        f'</tr>'
        for n in arch_notes
    )

    queue_section = (
        f'<div style="display:flex;align-items:center;gap:12px;margin-bottom:6px">'
        f'<h2 style="margin:0">Active Research Topics <span class="h2-count">{len(non_arch)}</span></h2>'
        f'<label style="font-size:11px;color:#333;display:flex;align-items:center;gap:5px;cursor:pointer;margin-left:auto">'
        f'<input type="checkbox" id="show-archived" onchange="toggleArchived(this.checked)" style="accent-color:#555">'
        f'Show {arch_ct} archived</label>'
        f'</div>'
        f'<div class="table-wrap"><table><thead><tr>'
        f'<th>Topic</th><th>Status</th><th>Priority</th><th>Type</th>'
        f'<th>Depth</th><th>Last Research</th><th></th>'
        f'</tr></thead>'
        f'<tbody id="active-rows">{topic_rows}</tbody>'
        f'<tbody id="arch-rows" style="display:none">{arch_rows}</tbody>'
        f'</table></div>'
        f'<script>function toggleArchived(on){{'
        f'document.getElementById("arch-rows").style.display=on?"":"none";}}</script>'
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

// ── Auto-refresh every 30s with countdown bar
var _refreshSecs=30;
var _refreshLeft=_refreshSecs;
var _bar=document.getElementById('refresh-bar');
setInterval(function(){
  _refreshLeft--;
  if(_bar) _bar.style.width=Math.round((_refreshLeft/_refreshSecs)*100)+'%';
  if(_refreshLeft<=0) location.reload();
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


# ── Sources audit ──────────────────────────────────────────────────────────────

_CRED_LABEL = {1: "academic", 2: "quality-news", 3: "general", 4: "aggregator", 5: "social"}
_CRED_COLOR = {1: "#6bcb77", 2: "#7dd3fc", 3: "#888888", 4: "#ffd93d", 5: "#ff6b6b"}

@app.get("/sources", response_class=HTMLResponse)
def sources_page(sort: str = "fetch_count", topic: str = "", cred: str = ""):
    import sqlite3 as _sqlite3
    db_path = cfg.get("memory.db_path", "data/memory.db")
    rows = []
    try:
        conn = _sqlite3.connect(db_path)
        conn.row_factory = _sqlite3.Row
        cur = conn.cursor()
        q = "SELECT url, domain, title, first_fetched, last_fetched, fetch_count, topic_slug, reliability FROM sources"
        filters, params = [], []
        if topic:
            filters.append("topic_slug = ?"); params.append(topic)
        if cred:
            try: filters.append("reliability = ?"); params.append(int(cred))
            except ValueError: pass
        if filters:
            q += " WHERE " + " AND ".join(filters)
        order = {"fetch_count": "fetch_count DESC", "domain": "domain ASC",
                 "last_fetched": "last_fetched DESC", "reliability": "reliability ASC"}.get(sort, "fetch_count DESC")
        q += f" ORDER BY {order}"
        rows = [dict(r) for r in cur.execute(q, params).fetchall()]
        conn.close()
    except Exception:
        pass

    # Pull article cache change data and merge in
    cache_changed = {}
    cache_fetched_at = {}
    try:
        import sqlite3 as _sq3
        cc = _sq3.connect("data/article_cache.db")
        cc.row_factory = _sq3.Row
        for cr in cc.execute("SELECT url, changed, fetched_at, fetch_count FROM article_cache").fetchall():
            cache_changed[cr["url"]] = bool(cr["changed"])
            cache_fetched_at[cr["url"]] = cr["fetched_at"]
        cc.close()
    except Exception:
        pass
    for r in rows:
        r["cache_changed"] = cache_changed.get(r["url"], False)
        r["cache_fetched_at"] = cache_fetched_at.get(r["url"], "")

    changed_count = sum(1 for r in rows if r["cache_changed"])

    # Summary stats
    total = len(rows)
    by_cred = {}
    for r in rows:
        k = r.get("reliability") or 3
        by_cred[k] = by_cred.get(k, 0) + 1
    domains = len({r["domain"] for r in rows})

    stats_html = (
        f'<div class="stats">'
        f'<div class="stat-card"><div class="stat-num">{total}</div><div class="stat-lbl">Sources</div></div>'
        f'<div class="stat-card"><div class="stat-num">{domains}</div><div class="stat-lbl">Domains</div></div>'
        f'<div class="stat-card"><div class="stat-num" style="color:#ffd93d">{changed_count}</div><div class="stat-lbl">Updated</div></div>'
        + "".join(
            f'<div class="stat-card"><div class="stat-num" style="color:{_CRED_COLOR.get(k,"#888")}">{v}</div>'
            f'<div class="stat-lbl">{_CRED_LABEL.get(k,str(k))}</div></div>'
            for k, v in sorted(by_cred.items())
        )
        + '</div>'
    )

    # Filter controls
    all_topics = sorted({r["topic_slug"] for r in rows if r.get("topic_slug")})
    topic_opts = '<option value="">All topics</option>' + "".join(
        f'<option value="{t}" {"selected" if t==topic else ""}>{t}</option>' for t in all_topics
    )
    cred_opts = '<option value="">All tiers</option>' + "".join(
        f'<option value="{k}" {"selected" if str(k)==cred else ""}>{_CRED_LABEL[k]}</option>'
        for k in sorted(_CRED_LABEL)
    )
    sort_opts = "".join(
        f'<option value="{v}" {"selected" if v==sort else ""}>{l}</option>'
        for v, l in [("fetch_count","Fetch Count"), ("domain","Domain"), ("last_fetched","Last Fetched"), ("reliability","Credibility")]
    )
    filter_bar = (
        f'<form method="get" style="display:flex;gap:8px;flex-wrap:wrap;margin-bottom:16px;align-items:center">'
        f'<select name="topic" onchange="this.form.submit()">{topic_opts}</select>'
        f'<select name="cred" onchange="this.form.submit()">{cred_opts}</select>'
        f'<select name="sort" onchange="this.form.submit()">{sort_opts}</select>'
        f'<a href="/sources" style="font-size:11px;color:#444;margin-left:4px">reset</a>'
        f'</form>'
    )

    # Table rows
    def _cred_badge(r):
        k = r.get("reliability") or 3
        col = _CRED_COLOR.get(k, "#888")
        lbl = _CRED_LABEL.get(k, str(k))
        return f'<span style="background:{col}22;color:{col};padding:1px 7px;border-radius:3px;font-size:10px">{lbl}</span>'

    def _short_url(url, n=60):
        return _html.escape(url[:n] + ("…" if len(url) > n else ""))

    def _change_badge(r):
        if r.get("cache_changed"):
            return '<span style="background:#2a1a00;color:#ffd93d;padding:1px 7px;border-radius:3px;font-size:10px" title="Content changed since first fetch">⚡ updated</span>'
        if r.get("cache_fetched_at"):
            return '<span style="color:#1a1a1a;font-size:10px">cached</span>'
        return '<span style="color:#1a1a1a;font-size:10px">—</span>'

    table_rows = "".join(
        f'<tr{"" if not r.get("cache_changed") else " style=background:#120f00"}">'
        f'<td style="max-width:320px;overflow:hidden"><a href="{_html.escape(r["url"])}" target="_blank" '
        f'style="color:var(--accent-dim);font-size:11px">{_short_url(r["url"])}</a></td>'
        f'<td style="color:#999;font-size:11px">{_html.escape(r["domain"] or "")}</td>'
        f'<td>{_cred_badge(r)}</td>'
        f'<td style="text-align:center;color:var(--accent)">{r["fetch_count"]}</td>'
        f'<td style="color:#444;font-size:11px">{str(r.get("last_fetched",""))[:10]}</td>'
        f'<td>{_change_badge(r)}</td>'
        f'<td><a href="/vault/{_html.escape(r["topic_slug"] or "")}" '
        f'style="color:#446;font-size:11px">{_html.escape(r["topic_slug"] or "")}</a></td>'
        f'</tr>'
        for r in rows
    ) or f'<tr><td colspan="7" class="empty">No sources yet</td></tr>'

    body = (
        f'<h1>Sources <span style="color:#333;font-size:13px">audit log</span></h1>'
        + stats_html + filter_bar
        + '<div class="table-wrap"><table><thead><tr>'
        + '<th>URL</th><th>Domain</th><th>Credibility</th><th>Fetches</th><th>Last Seen</th><th>Cache</th><th>Topic</th>'
        + f'</tr></thead><tbody>{table_rows}</tbody></table></div>'
    )
    return _page("Sources", body, "sources")


# ── Vault search ────────────────────────────────────────────────────────────────

@app.get("/search", response_class=HTMLResponse)
def vault_search(q: str = ""):
    results = []
    if q.strip():
        q_lower = q.lower()
        for note in _topics.list_topics():
            body = note.body or ""
            name = note.name or ""
            # score: title match = 10pts, body match = count of occurrences
            title_score = 10 if q_lower in name.lower() else 0
            body_score = body.lower().count(q_lower)
            score = title_score + body_score
            if score > 0:
                # Find a short excerpt around the first match
                idx = body.lower().find(q_lower)
                if idx >= 0:
                    start = max(0, idx - 80)
                    end = min(len(body), idx + 120)
                    excerpt = ("…" if start > 0 else "") + body[start:end].replace("\n", " ") + ("…" if end < len(body) else "")
                    # Highlight the match
                    hi = body[idx:idx+len(q)]
                    excerpt = excerpt.replace(hi, f'<mark style="background:#2a1a00;color:#ffd93d;padding:0 2px">{_html.escape(hi)}</mark>', 1)
                else:
                    excerpt = body[:200].replace("\n", " ") + "…"
                results.append({"note": note, "score": score, "excerpt": excerpt})
        results.sort(key=lambda x: -x["score"])

    result_html = ""
    if q.strip() and not results:
        result_html = '<div class="empty" style="padding:40px 0;text-align:center">No results found for <strong>' + _html.escape(q) + '</strong></div>'
    elif results:
        result_html = f'<div style="color:#444;font-size:11px;margin-bottom:16px">{len(results)} result{"s" if len(results)!=1 else ""} for <span style="color:#ccc">"{_html.escape(q)}"</span></div>'
        for r in results:
            n = r["note"]
            snap_count = _memory.get_note_snapshot_count(n.slug)
            result_html += (
                f'<div style="border:1px solid #1a1a1a;border-radius:4px;padding:14px 16px;margin-bottom:10px;background:#0d0d0d">'
                f'<div style="display:flex;align-items:baseline;gap:10px;margin-bottom:6px">'
                f'<a href="/vault/{n.slug}" style="color:#fff;font-size:14px;font-weight:bold">{_html.escape(n.name)}</a>'
                f'<span style="color:#444;font-size:10px">{n.type}</span>'
                f'{_badge(n.priority)}'
                f'<span style="margin-left:auto;color:#333;font-size:10px">depth {n.research_depth} · {snap_count} run{"s" if snap_count!=1 else ""}</span>'
                f'</div>'
                f'<div style="color:#666;font-size:12px;line-height:1.6">{r["excerpt"]}</div>'
                f'</div>'
            )

    body = (
        f'<h1>Search Vault</h1>'
        f'<form method="get" style="display:flex;gap:8px;margin-bottom:24px">'
        f'<input type="text" name="q" value="{_html.escape(q)}" placeholder="Search notes…" autofocus'
        f' style="flex:1;max-width:480px;padding:8px 12px;background:#111;border:1px solid #2a2a2a;'
        f'color:#ccc;border-radius:3px;font-family:inherit;font-size:13px">'
        f'<button type="submit" class="btn-green" style="padding:8px 18px">Search</button>'
        f'{"<a href=/search><button class=btn-dim style=padding:8px>✕</button></a>" if q else ""}'
        f'</form>'
        f'{result_html}'
    )
    return _page("Search", body, "search")


# ── Note history / diff ─────────────────────────────────────────────────────────

@app.get("/vault/{slug}/history", response_class=HTMLResponse)
def note_history(slug: str):
    note = _vault.read_note(slug)
    if not note:
        return _page("Not Found", f'<div class="alert alert-warn">Note not found: {_html.escape(slug)}</div>', "vault")

    snapshots = _memory.get_note_history(slug)
    if not snapshots:
        return _page(f"History: {note.name}",
            f'<h1>History: {_html.escape(note.name)}</h1>'
            f'<div class="empty" style="padding:40px 0;text-align:center">No history yet — snapshots are saved each time the agent rewrites this note.</div>',
            "vault")

    import difflib

    def _diff_html(old_text: str, new_text: str) -> str:
        old_lines = old_text.splitlines(keepends=True)
        new_lines = new_text.splitlines(keepends=True)
        diff = list(difflib.unified_diff(old_lines, new_lines, lineterm="", n=2))
        if not diff:
            return '<div style="color:#333;font-size:11px;padding:8px">No textual changes detected.</div>'
        html_lines = []
        for line in diff[3:]:  # skip @@-header lines
            if line.startswith("@@"):
                html_lines.append(f'<div style="color:#446;padding:2px 6px;font-size:10px">{_html.escape(line)}</div>')
            elif line.startswith("+"):
                html_lines.append(f'<div style="background:#0a1a0a;color:#6bcb77;padding:1px 6px">{_html.escape(line)}</div>')
            elif line.startswith("-"):
                html_lines.append(f'<div style="background:#1a0a0a;color:#ff6b6b;padding:1px 6px">{_html.escape(line)}</div>')
            else:
                html_lines.append(f'<div style="color:#444;padding:1px 6px">{_html.escape(line)}</div>')
        return "".join(html_lines)

    # Build timeline: current vs each snapshot, and snapshots vs each other
    # snapshots[0] = most recent (before current), snapshots[1] = before that, etc.
    current_body = note.body or ""
    versions = [{"label": "Current", "body": current_body, "saved_at": "now",
                 "depth": note.research_depth, "word_count": len(current_body.split())}]
    for s in snapshots:
        versions.append({"label": f'Run #{s["run_number"]}', "body": s["body"],
                         "saved_at": s["saved_at"][:16], "depth": s["depth"],
                         "word_count": s["word_count"]})

    sections = []
    for i in range(len(versions) - 1):
        newer = versions[i]
        older = versions[i + 1]
        words_delta = newer["word_count"] - older["word_count"]
        delta_col = "#6bcb77" if words_delta >= 0 else "#ff6b6b"
        delta_str = f'{"+" if words_delta >= 0 else ""}{words_delta} words'
        sections.append(
            f'<div style="border:1px solid #1a1a2a;border-radius:4px;margin-bottom:18px;overflow:hidden">'
            f'<div style="background:#0d0d12;padding:10px 14px;display:flex;align-items:center;gap:12px;border-bottom:1px solid #1a1a2a">'
            f'<span style="color:#a78bfa;font-weight:bold">{newer["label"]}</span>'
            f'<span style="color:#333">→</span>'
            f'<span style="color:#555">{older["label"]}</span>'
            f'<span style="color:#444;font-size:10px">{older["saved_at"]}</span>'
            f'<span style="margin-left:auto;color:{delta_col};font-size:11px">{delta_str}</span>'
            f'<span style="color:#333;font-size:10px">depth {older["depth"]} → {newer["depth"]}</span>'
            f'</div>'
            f'<div style="font-family:monospace;font-size:11px;line-height:1.5;max-height:400px;overflow-y:auto">'
            f'{_diff_html(older["body"], newer["body"])}'
            f'</div></div>'
        )

    body = (
        f'<div style="display:flex;align-items:center;gap:12px;margin-bottom:20px">'
        f'<h1 style="margin:0">History: {_html.escape(note.name)}</h1>'
        f'<span style="color:#333">{len(snapshots)} snapshot{"s" if len(snapshots)!=1 else ""}</span>'
        f'<a href="/vault/{slug}" style="margin-left:auto"><button class="btn-dim">← Back to Note</button></a>'
        f'</div>'
        f'<div style="color:#444;font-size:11px;margin-bottom:20px">'
        f'Green = added &nbsp;·&nbsp; Red = removed &nbsp;·&nbsp; Showing {len(sections)} diff{"s" if len(sections)!=1 else ""}'
        f'</div>'
        + "".join(sections)
    )
    return _page(f"History: {note.name}", body, "vault")


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
        # Check if it looks like a frontier/ghost node (referenced but not yet researched)
        display_name = slug.replace("-", " ").title()
        ghost_body = (
            f'<div style="text-align:center;padding:60px 20px">'
            f'<div style="font-size:48px;margin-bottom:16px;opacity:0.3">◌</div>'
            f'<h2 style="color:#446677;margin-bottom:8px">{_html.escape(display_name)}</h2>'
            f'<p style="color:#333;margin-bottom:24px">This topic has been referenced but not yet researched.</p>'
            f'<form method="post" action="/topics/new" style="display:inline">'
            f'<input type="hidden" name="name" value="{_html.escape(display_name)}">'
            f'<input type="hidden" name="type" value="research">'
            f'<input type="hidden" name="priority" value="medium">'
            f'<button class="btn-green" style="padding:10px 24px;font-size:14px">+ Queue for Research</button>'
            f'</form>'
            f' &nbsp; <a href="/vault"><button class="btn-dim">← Back to Vault</button></a>'
            f'</div>'
        )
        return _page(f"Frontier: {display_name}", ghost_body, "vault")

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
        f'<a href="/vault/{note.slug}/history"><button class="btn-dim">⏱ History</button></a>'
        f'<form method="post" action="/topics/{note.slug}/queue"><button>↺ Requeue</button></form>'
        f'<form method="post" action="/topics/{note.slug}/archive"><button class="btn-danger">Archive</button></form>'
        '<a href="/vault"><button class="btn-dim">← Back</button></a>'
        '</div>'
    )
    # ── Sources with credibility scores ────────────────────────────────────────
    _CRED_LABEL = {1: "academic", 2: "quality-news", 3: "general", 4: "aggregator", 5: "social"}
    _CRED_COLOR = {1: "#6bcb77", 2: "#7dd3fc", 3: "#888888", 4: "#ffd93d", 5: "#ff6b6b"}
    sources_html = ""
    try:
        srcs = _memory.get_sources_for_topic(note.slug)
        if srcs:
            rows = []
            for s in srcs:
                r    = s.get("reliability") or 3
                col  = _CRED_COLOR.get(r, "#888888")
                lbl  = _CRED_LABEL.get(r, "general")
                url  = _html.escape(s.get("url", ""))
                dom  = _html.escape(s.get("domain", url[:40]))
                cnt  = s.get("fetch_count", 1)
                date = (s.get("last_fetched") or "")[:10]
                score_badge = f'<span style="color:{col};font-size:10px;padding:1px 5px;border:1px solid {col}44;border-radius:9px">{lbl} {r}/5</span>'
                rows.append(
                    f'<tr><td><a href="{url}" target="_blank" rel="noopener">{dom}</a></td>'
                    f'<td>{score_badge}</td>'
                    f'<td style="color:#555">{cnt}×</td>'
                    f'<td style="color:#444">{date}</td></tr>'
                )
            sources_html = (
                '<h2>Sources</h2>'
                '<div class="table-wrap"><table>'
                '<thead><tr><th>URL</th><th>Credibility</th><th>Fetched</th><th>Date</th></tr></thead>'
                '<tbody>' + ''.join(rows) + '</tbody></table></div>'
            )
    except Exception:
        pass

    rendered = _render_markdown(note.body or "")
    raw_escaped = _html.escape(note.body or "")
    content_section = f"""
<h2>Note Content
  <span style="margin-left:auto;display:inline-flex;gap:4px">
    <button class="btn-sm btn-dim" onclick="showTab('rendered')" id="tab-rendered">Rendered</button>
    <button class="btn-sm btn-dim" onclick="showTab('raw')" id="tab-raw">Raw</button>
  </span>
</h2>
<div id="pane-rendered" class="md-body">{rendered}</div>
<div id="pane-raw" style="display:none"><pre>{raw_escaped}</pre></div>
{sources_html}
<script>
function showTab(t){{
  document.getElementById('pane-rendered').style.display = t==='rendered'?'':'none';
  document.getElementById('pane-raw').style.display      = t==='raw'?'':'none';
  document.getElementById('tab-rendered').style.color    = t==='rendered'?'var(--accent)':'';
  document.getElementById('tab-raw').style.color         = t==='raw'?'var(--accent)':'';
}}
showTab('rendered');
</script>"""
    return _page(note.name, f'<h1>{_html.escape(note.name)}</h1>{actions}{meta}{content_section}', "vault")


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
        '<input type="hidden" name="redirect" value="/topics">'
        '<div class="row"><input type="submit" value="Create Topic"></div>'
        '</form></details>'
    )
    return _page("Topics", (
        f'<h1>Topics <span style="color:#444;font-size:13px">({len(notes)})</span></h1>'
        f'<div style="margin-bottom:10px;color:#555;font-size:11px">Filter: {filters}</div>'
        f'<table><thead><tr><th>Name</th><th>Status</th><th>Priority</th><th>Type</th>'
        f'<th>Tags</th><th>Last Research</th><th></th></tr></thead>'
        f'<tbody>{rows}</tbody></table>{new_form}'
    ), "topics")


@app.post("/topics/new")
async def new_topic(request: Request):
    form  = await request.form()
    name  = str(form.get("name", "")).strip()
    ttype = str(form.get("type", "research"))
    prio  = str(form.get("priority", "medium"))
    tags  = [t.strip() for t in str(form.get("tags", "")).split(",") if t.strip()]
    redirect = str(form.get("redirect", "")).strip()  # optional: where to go after
    if name:
        slug = _vault.name_to_slug(name)
        try:
            _topics.create_topic(name, type=ttype, priority=prio, tags=tags)
        except ValueError:
            pass  # already exists — still redirect to its vault page
        dest = redirect or f"/vault/{slug}"
        return RedirectResponse(dest, status_code=303)
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


# ── Graph API ──────────────────────────────────────────────────────────────────

@app.get("/api/graph")
def api_graph():
    notes    = _topics.list_topics()
    slug_set = {n.slug for n in notes}
    nodes    = []
    edges    = []
    seen_edges = set()

    # Real nodes
    for n in notes:
        nodes.append({
            "id":     n.slug,
            "name":   n.name,
            "type":   n.type or "research",
            "depth":  n.research_depth,
            "status": n.status,
            "runs":   n.research_runs,
            "tags":   n.tags or [],
            "ghost":  False,
        })

    # WikiLink edges — vault-to-vault where target exists
    # Also build ghost nodes for links that point outside the vault
    ghost_nodes = {}  # name -> ghost node dict
    for n in notes:
        for link in (n.forward_links or []):
            target_slug = _vault.name_to_slug(link)
            if target_slug == n.slug:
                continue  # skip self-loops
            key = (n.slug, target_slug)
            if key in seen_edges:
                continue
            seen_edges.add(key)
            if target_slug in slug_set:
                edges.append({"source": n.slug, "target": target_slug, "kind": "link"})
            else:
                # Ghost node — referenced but not yet researched
                gid = "ghost:" + target_slug
                if gid not in ghost_nodes:
                    ghost_nodes[gid] = {
                        "id":     gid,
                        "name":   link,
                        "type":   "ghost",
                        "depth":  0,
                        "status": "unresearched",
                        "runs":   0,
                        "tags":   [],
                        "ghost":  True,
                    }
                gkey = (n.slug, gid)
                if gkey not in seen_edges:
                    seen_edges.add(gkey)
                    edges.append({"source": n.slug, "target": gid, "kind": "link"})

    nodes.extend(ghost_nodes.values())

    # Tag-shared edges — connect real notes that share a tag
    from collections import defaultdict
    tag_map = defaultdict(list)
    for n in notes:
        for t in (n.tags or []):
            if t:
                tag_map[t].append(n.slug)
    for tag, slugs in tag_map.items():
        if len(slugs) < 2:
            continue
        for i in range(len(slugs)):
            for j in range(i + 1, len(slugs)):
                a, b = slugs[i], slugs[j]
                key = tuple(sorted([a, b])) + ("tag",)
                if key not in seen_edges:
                    seen_edges.add(key)
                    edges.append({"source": a, "target": b, "kind": "tag", "label": tag})

    return JSONResponse({"nodes": nodes, "edges": edges})


@app.get("/graph", response_class=HTMLResponse)
def graph_page():
    body = f"""
<div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:12px;flex-wrap:wrap;gap:8px">
  <h1 style="margin:0">Research Graph</h1>
  <div style="display:flex;gap:8px;align-items:center;flex-wrap:wrap">
    <span id="graph-stats" style="color:#333;font-size:11px">loading...</span>
    <button class="btn-sm btn-dim" onclick="resetView()">&#8857; Reset</button>
    <button class="btn-sm btn-dim" onclick="toggleLabels()" id="btn-labels">&#9707; Labels</button>
    <button class="btn-sm btn-dim" onclick="toggleTags()" id="btn-tags" style="color:#a78bfa">&#8764; Tags</button>
    <button class="btn-sm btn-dim" onclick="toggleGhosts()" id="btn-ghosts" style="color:#444">&#9702; Frontier</button>
  </div>
</div>
<div class="graph-legend">
  <span class="legend-item"><span class="legend-dot" style="background:#7dd3fc"></span>tech</span>
  <span class="legend-item"><span class="legend-dot" style="background:#c4b5fd"></span>person</span>
  <span class="legend-item"><span class="legend-dot" style="background:#fde68a"></span>concept</span>
  <span class="legend-item"><span class="legend-dot" style="background:#6bcb77"></span>research</span>
  <span class="legend-item"><span class="legend-dot" style="background:#fb923c"></span>event</span>
  <span class="legend-item" style="opacity:0.5"><span class="legend-dot" style="background:#444;border:1px dashed #666"></span>frontier</span>
  <span class="legend-item" style="margin-left:12px"><span style="display:inline-block;width:22px;height:2px;background:linear-gradient(90deg,#7dd3fc,#c4b5fd);margin-right:4px;vertical-align:middle"></span>wiki&nbsp;link</span>
  <span class="legend-item"><span style="display:inline-block;width:22px;height:2px;border-top:1px dashed #a78bfa55;margin-right:4px;vertical-align:middle"></span>shared&nbsp;tag</span>
  <span class="legend-item" style="margin-left:12px"><span class="legend-dot" style="background:#ffd93d;border-radius:2px"></span>depth&nbsp;&#8805;3</span>
  <span style="margin-left:auto;color:#333;font-size:10px">scroll=zoom &nbsp; drag=pan &nbsp; drag node=pin &nbsp; click=select &nbsp; dbl-click=open</span>
</div>
<canvas id="graph-canvas"></canvas>
<div id="graph-tooltip"></div>
<div id="graph-info" style="color:#444">Loading graph...</div>
<script>
(function(){{
var TYPE_COLOR={{tech:'#7dd3fc',person:'#c4b5fd',concept:'#fde68a',research:'#6bcb77',event:'#fb923c'}};
function nc(t){{return TYPE_COLOR[t]||'#888888';}}
/* expand 3-char hex (#abc -> #aabbcc) before parsing */
function h2r(h){{
  if(h.length===4) h='#'+h[1]+h[1]+h[2]+h[2]+h[3]+h[3];
  return[parseInt(h.slice(1,3),16),parseInt(h.slice(3,5),16),parseInt(h.slice(5,7),16)];
}}
/* roundRect polyfill for older browsers */
function roundRect(ctx,x,y,w,h,r){{
  ctx.beginPath();ctx.moveTo(x+r,y);ctx.lineTo(x+w-r,y);
  ctx.arcTo(x+w,y,x+w,y+r,r);ctx.lineTo(x+w,y+h-r);
  ctx.arcTo(x+w,y+h,x+w-r,y+h,r);ctx.lineTo(x+r,y+h);
  ctx.arcTo(x,y+h,x,y+h-r,r);ctx.lineTo(x,y+r);
  ctx.arcTo(x,y,x+r,y,r);ctx.closePath();
}}

var canvas=document.getElementById('graph-canvas');
var ctx=canvas.getContext('2d');
var tooltip=document.getElementById('graph-tooltip');
var info=document.getElementById('graph-info');
var statsEl=document.getElementById('graph-stats');

/* viewport */
var vx=0,vy=0,vs=1;
var panning=false,panS={{x:0,y:0}},panO={{x:0,y:0}};
function tw(sx,sy){{return[(sx-vx)/vs,(sy-vy)/vs];}}

function resize(){{
  var w=canvas.parentElement.clientWidth-2;
  canvas.width=Math.max(640,w);
  canvas.height=Math.round(Math.max(500,w*0.60));
  canvas.style.width='100%';
  canvas.style.height=canvas.height+'px';
}}
resize();
window.addEventListener('resize',function(){{resize();draw();}});

/* state */
var nodes=[],edges=[],nodeMap={{}};
var allEdges=[];   /* full set */
var hoveredId=null,selectedId=null,dragNode=null;
var showLabels=true,showTags=true,showGhosts=true;
var particles=[];
var simAlpha=0;

/* toggles — exposed to window so onclick= attributes can reach them */
function resetView(){{vx=0;vy=0;vs=1;}}
function toggleLabels(){{
  showLabels=!showLabels;
  document.getElementById('btn-labels').style.opacity=showLabels?1:0.4;
}}
function toggleTags(){{
  showTags=!showTags;
  document.getElementById('btn-tags').style.opacity=showTags?1:0.4;
  rebuildEdges();
}}
function toggleGhosts(){{
  showGhosts=!showGhosts;
  document.getElementById('btn-ghosts').style.opacity=showGhosts?1:0.4;
  rebuildEdges();
}}
window.resetView=resetView;
window.toggleLabels=toggleLabels;
window.toggleTags=toggleTags;
window.toggleGhosts=toggleGhosts;
function rebuildEdges(){{
  edges=allEdges.filter(function(e){{
    if(!showTags&&e.kind==='tag') return false;
    var s=nodeMap[e.source],t=nodeMap[e.target];
    if(!s||!t) return false;
    if(!showGhosts&&(s.ghost||t.ghost)) return false;
    return true;
  }});
  spawnParticles();
}}

/* radius: ghost nodes smaller */
function nr(n){{
  if(n.ghost) return 4/vs;
  return(6+Math.min(n.depth||0,6)*2.4)/vs;
}}

/* neighbours */
function neighbours(id){{
  var s=new Set();
  edges.forEach(function(e){{
    if(e.source===id)s.add(e.target);
    if(e.target===id)s.add(e.source);
  }});
  return s;
}}

/* bezier ctrl */
function cp(ax,ay,bx,by){{
  var mx=(ax+bx)/2,my=(ay+by)/2,dx=bx-ax,dy=by-ay,d=Math.sqrt(dx*dx+dy*dy)+0.01;
  var off=Math.min(55,d*0.22);
  return[mx-dy/d*off,my+dx/d*off];
}}

/* fetch & init */
fetch('/api/graph').then(function(r){{return r.json();}}).then(function(data){{
  nodes=data.nodes; allEdges=data.edges;
  nodes.forEach(function(n){{nodeMap[n.id]=n;}});
  rebuildEdges();
  layout();
  spawnParticles();
  startSim();
  loop();
  /* stats */
  var real=nodes.filter(function(n){{return!n.ghost;}});
  var ghosts=nodes.filter(function(n){{return n.ghost;}});
  var links=allEdges.filter(function(e){{return e.kind==='link';}});
  var tags=allEdges.filter(function(e){{return e.kind==='tag';}});
  statsEl.textContent=real.length+' notes  ·  '+ghosts.length+' frontier  ·  '+links.length+' links  ·  '+tags.length+' tag connections';
}});

function layout(){{
  var W=canvas.width/vs,H=canvas.height/vs;
  nodes.forEach(function(n,i){{
    if(n.x===undefined){{
      var a=(i/nodes.length)*Math.PI*2;
      var r=n.ghost?W*0.38:W*0.26;
      n.x=W/2+Math.cos(a)*r+(Math.random()-.5)*40;
      n.y=H/2+Math.sin(a)*r+(Math.random()-.5)*40;
    }}
    n.vx=0;n.vy=0;n.pinned=false;
  }});
}}

/* particles — only on link edges */
function spawnParticles(){{
  particles=[];
  edges.filter(function(e){{return e.kind==='link';}}).forEach(function(e){{
    var n=1+Math.floor(Math.random()*2);
    for(var i=0;i<n;i++)
      particles.push({{e:e,t:Math.random(),spd:0.0007+Math.random()*0.0009}});
  }});
}}

/* physics */
function startSim(){{
  simAlpha=1.0;
  function tick(){{
    if(simAlpha<0.002)return;
    simAlpha*=0.973;
    var W=canvas.width/vs,H=canvas.height/vs;
    var REP=3800,SPR=0.05,CEN=0.009;
    for(var a=0;a<nodes.length;a++){{
      for(var b=a+1;b<nodes.length;b++){{
        var na=nodes[a],nb=nodes[b];
        var dx=nb.x-na.x,dy=nb.y-na.y,d2=dx*dx+dy*dy+1,d=Math.sqrt(d2);
        var f=REP/d2*simAlpha;
        na.vx-=dx/d*f;na.vy-=dy/d*f;nb.vx+=dx/d*f;nb.vy+=dy/d*f;
      }}
    }}
    edges.forEach(function(e){{
      var s=nodeMap[e.source],t=nodeMap[e.target];if(!s||!t)return;
      var dx=t.x-s.x,dy=t.y-s.y,d=Math.sqrt(dx*dx+dy*dy)+0.01;
      var rest=e.kind==='tag'?160:120;
      var f=(d-rest)*SPR*simAlpha;
      s.vx+=dx/d*f;s.vy+=dy/d*f;t.vx-=dx/d*f;t.vy-=dy/d*f;
    }});
    nodes.forEach(function(n){{
      n.vx+=(W/2-n.x)*CEN*simAlpha;
      n.vy+=(H/2-n.y)*CEN*simAlpha;
    }});
    nodes.forEach(function(n){{
      if(n.pinned||n===dragNode)return;
      n.x+=n.vx;n.y+=n.vy;n.vx*=0.70;n.vy*=0.70;
      n.x=Math.max(20,Math.min(W-20,n.x));
      n.y=Math.max(20,Math.min(H-20,n.y));
    }});
    requestAnimationFrame(tick);
  }}
  requestAnimationFrame(tick);
}}

function loop(){{
  particles.forEach(function(p){{p.t=(p.t+p.spd)%1;}});
  draw();
  requestAnimationFrame(loop);
}}

function draw(){{
  ctx.clearRect(0,0,canvas.width,canvas.height);
  ctx.save();
  ctx.translate(vx,vy);ctx.scale(vs,vs);

  var focId=selectedId||hoveredId;
  var nb=focId?neighbours(focId):null;
  var hasFoc=focId!==null;

  /* ── tag edges (dashed, drawn first, dimmer) ── */
  edges.filter(function(e){{return e.kind==='tag';}}).forEach(function(e){{
    var s=nodeMap[e.source],t=nodeMap[e.target];if(!s||!t)return;
    if(s.ghost||t.ghost)return;
    var isFoc=hasFoc&&(e.source===focId||e.target===focId);
    var fade=hasFoc&&!isFoc;
    var a=fade?0.04:(isFoc?0.5:0.14);
    ctx.beginPath();
    ctx.moveTo(s.x,s.y);ctx.lineTo(t.x,t.y);
    ctx.strokeStyle='rgba(167,139,250,'+a+')';
    ctx.lineWidth=(isFoc?1.5:0.8)/vs;
    ctx.setLineDash([5/vs,4/vs]);
    ctx.stroke();
    ctx.setLineDash([]);
    /* tag label on focused */
    if(isFoc&&e.label){{
      var mx=(s.x+t.x)/2,my=(s.y+t.y)/2;
      ctx.font='9px Consolas,monospace';
      ctx.textAlign='center';
      ctx.fillStyle='rgba(167,139,250,0.7)';
      ctx.fillText('#'+e.label,mx,my-5/vs);
    }}
  }});

  /* ── link edges (curved gradient + arrowhead) ── */
  edges.filter(function(e){{return e.kind==='link';}}).forEach(function(e){{
    var s=nodeMap[e.source],t=nodeMap[e.target];if(!s||!t)return;
    var isFoc=hasFoc&&(e.source===focId||e.target===focId);
    var fade=hasFoc&&!isFoc;
    var c=cp(s.x,s.y,t.x,t.y);
    var scol=s.ghost?'#445566':nc(s.type), tcol=t.ghost?'#445566':nc(t.type);
    var [sr,sg,sb]=h2r(scol),[tr2,tg,tb]=h2r(tcol);
    var a=fade?0.06:(isFoc?0.8:0.3);
    var grad=ctx.createLinearGradient(s.x,s.y,t.x,t.y);
    grad.addColorStop(0,'rgba('+sr+','+sg+','+sb+','+a+')');
    grad.addColorStop(1,'rgba('+tr2+','+tg+','+tb+','+a+')');
    ctx.beginPath();
    ctx.moveTo(s.x,s.y);
    ctx.quadraticCurveTo(c[0],c[1],t.x,t.y);
    ctx.strokeStyle=grad;
    ctx.lineWidth=(isFoc?2.2:1)/vs;
    ctx.stroke();
    /* arrowhead */
    if(!fade){{
      var bt=0.82;
      var bx=(1-bt)*(1-bt)*s.x+2*(1-bt)*bt*c[0]+bt*bt*t.x;
      var by=(1-bt)*(1-bt)*s.y+2*(1-bt)*bt*c[1]+bt*bt*t.y;
      var ang=Math.atan2(t.y-by,t.x-bx);
      var rr=nr(t)+2/vs;
      var ax=t.x-Math.cos(ang)*rr,ay=t.y-Math.sin(ang)*rr;
      var asz=(isFoc?8:5)/vs;
      ctx.beginPath();
      ctx.moveTo(ax,ay);
      ctx.lineTo(ax-asz*Math.cos(ang-0.42),ay-asz*Math.sin(ang-0.42));
      ctx.lineTo(ax-asz*Math.cos(ang+0.42),ay-asz*Math.sin(ang+0.42));
      ctx.closePath();
      ctx.fillStyle='rgba('+tr2+','+tg+','+tb+','+(isFoc?0.95:0.4)+')';
      ctx.fill();
    }}
  }});

  /* ── particles ── */
  particles.forEach(function(p){{
    var s=nodeMap[p.e.source],t=nodeMap[p.e.target];if(!s||!t)return;
    var isFoc=hasFoc&&(p.e.source===focId||p.e.target===focId);
    if(hasFoc&&!isFoc)return;
    var c=cp(s.x,s.y,t.x,t.y),tt=p.t;
    var bx=(1-tt)*(1-tt)*s.x+2*(1-tt)*tt*c[0]+tt*tt*t.x;
    var by=(1-tt)*(1-tt)*s.y+2*(1-tt)*tt*c[1]+tt*tt*t.y;
    var col=s.ghost?'#445566':nc(s.type);
    var[pr,pg,pb]=h2r(col);
    ctx.beginPath();
    ctx.arc(bx,by,isFoc?2.2/vs:1.4/vs,0,Math.PI*2);
    ctx.fillStyle='rgba('+pr+','+pg+','+pb+','+(isFoc?0.95:0.6)+')';
    ctx.shadowColor=col;ctx.shadowBlur=isFoc?8:4;
    ctx.fill();ctx.shadowBlur=0;
  }});

  /* ── nodes ── */
  nodes.forEach(function(n){{
    if(n.ghost&&!showGhosts)return;
    var r=nr(n);
    var col=n.ghost?'#334455':nc(n.type);
    var isFoc=n.id===focId;
    var isN=nb&&nb.has(n.id);
    var fade=hasFoc&&!isFoc&&!isN;
    var[cr,cg,cb]=h2r(n.ghost?'#556677':col); /* col is always 6-char */

    /* depth ring */
    if(!n.ghost&&n.depth>=3&&!fade){{
      ctx.beginPath();
      ctx.arc(n.x,n.y,r+4/vs,0,Math.PI*2);
      ctx.strokeStyle='rgba(255,217,61,'+(isFoc?0.65:0.22)+')';
      ctx.lineWidth=1.4/vs;ctx.stroke();
    }}

    if(isFoc){{ctx.shadowColor=col;ctx.shadowBlur=24;}}

    ctx.beginPath();ctx.arc(n.x,n.y,r,0,Math.PI*2);
    var fa=fade?0.12:(isFoc?1:(isN?0.75:0.55));
    ctx.fillStyle=n.ghost
      ?'rgba(30,40,50,'+(fade?0.1:(isFoc?0.9:0.4))+')'
      :'rgba('+cr+','+cg+','+cb+','+fa+')';
    ctx.strokeStyle=n.ghost
      ?'rgba(80,110,140,'+(fade?0.1:(isFoc?0.8:0.35))+')'
      :'rgba('+cr+','+cg+','+cb+','+(fade?0.1:(isFoc?1:0.5))+')';
    ctx.lineWidth=(isFoc?2.5:(n.ghost?0.8:1))/vs;
    /* ghost: dashed border */
    if(n.ghost)ctx.setLineDash([3/vs,2/vs]);
    ctx.fill();ctx.stroke();
    if(n.ghost)ctx.setLineDash([]);
    ctx.shadowBlur=0;

    /* selected spinner ring */
    if(n.id===selectedId){{
      ctx.beginPath();
      ctx.arc(n.x,n.y,r+6/vs,0,Math.PI*2);
      ctx.strokeStyle='rgba('+cr+','+cg+','+cb+',0.45)';
      ctx.lineWidth=1/vs;
      ctx.setLineDash([4/vs,3/vs]);
      ctx.stroke();ctx.setLineDash([]);
    }}

    /* label */
    if(showLabels&&(!fade||(isFoc||isN))){{
      var ghost=n.ghost;
      var fs=ghost?9:Math.max(9,Math.min(12,r*vs*0.85+8));
      ctx.font=(isFoc&&!ghost?'bold ':'')+fs/vs+'px Consolas,monospace';
      ctx.textAlign='center';
      var lbl=n.name.length>26?n.name.slice(0,24)+'…':n.name;
      var tw2=ctx.measureText(lbl).width;
      var lx=n.x,ly=n.y+r+12/vs;
      ctx.fillStyle='rgba(8,8,10,0.75)';
      roundRect(ctx,lx-tw2/2-3/vs,ly-fs/vs,tw2+6/vs,fs*1.35/vs,2/vs);
      ctx.fill();
      ctx.fillStyle=fade?'#333':(ghost?(isFoc?'#99bbcc':'#446677'):(isFoc?'#fff':(isN?'#ddd':'#888')));
      ctx.fillText(lbl,lx,ly);
    }}
  }});

  ctx.restore();
}}

/* hit test — generous radius so nodes are easy to click */
function nodeAt(sx,sy){{
  var[wx,wy]=tw(sx,sy);
  /* pass 1: check actual visual radius + 14px touch slop */
  for(var i=nodes.length-1;i>=0;i--){{
    var n=nodes[i];
    if(n.ghost&&!showGhosts)continue;
    var r=nr(n)+14/vs,dx=wx-n.x,dy=wy-n.y;
    if(dx*dx+dy*dy<=r*r)return n;
  }}
  return null;
}}

/* zoom */
canvas.addEventListener('wheel',function(e){{
  e.preventDefault();
  var rect=canvas.getBoundingClientRect();
  var mx=e.clientX-rect.left,my=e.clientY-rect.top;
  var d=e.deltaY>0?0.88:1.13;
  vs=Math.max(0.25,Math.min(6,vs*d));
  vx=mx-(mx-vx)*d;vy=my-(my-vy)*d;
}},{{passive:false}});

/* mouse */
var _mouseDownX=0,_mouseDownY=0,_wasDrag=false;
var DRAG_THRESHOLD=5; /* px — must move this far before suppressing click */
canvas.addEventListener('mousedown',function(e){{
  var rect=canvas.getBoundingClientRect();
  var sx=e.clientX-rect.left,sy=e.clientY-rect.top;
  var n=nodeAt(sx,sy);
  _mouseDownX=e.clientX;_mouseDownY=e.clientY;
  _wasDrag=false;
  if(n){{
    dragNode=n;n.pinned=true;
    /* select immediately on press so it feels instant */
    selectedId=n.id;
  }}
  else{{panning=true;panS={{x:e.clientX,y:e.clientY}};panO={{x:vx,y:vy}};canvas.style.cursor='grabbing';}}
}});

canvas.addEventListener('mousemove',function(e){{
  var rect=canvas.getBoundingClientRect();
  var sx=e.clientX-rect.left,sy=e.clientY-rect.top;
  if(dragNode){{
    var moved=Math.abs(e.clientX-_mouseDownX)+Math.abs(e.clientY-_mouseDownY);
    if(moved>DRAG_THRESHOLD)_wasDrag=true;
    var[wx,wy]=tw(sx,sy);dragNode.x=wx;dragNode.y=wy;return;
  }}
  if(panning){{
    var moved=Math.abs(e.clientX-_mouseDownX)+Math.abs(e.clientY-_mouseDownY);
    if(moved>DRAG_THRESHOLD)_wasDrag=true;
    vx=panO.x+(e.clientX-panS.x);vy=panO.y+(e.clientY-panS.y);return;
  }}
  var n=nodeAt(sx,sy);
  hoveredId=n?n.id:null;
  if(n){{
    canvas.style.cursor='pointer';
    var ghost=n.ghost;
    var[cr,cg,cb]=h2r(ghost?'#7799aa':nc(n.type)); /* both are always 6-char */
    tooltip.style.display='block';
    tooltip.style.left=(e.clientX+14)+'px';
    tooltip.style.top=(e.clientY-10)+'px';
    tooltip.innerHTML='<span style="color:rgb('+cr+','+cg+','+cb+')">'
      +'<strong>'+n.name+'</strong></span><br>'
      +(ghost?'<em style="color:#446">frontier — not yet researched</em>'
        :'<span style="color:#555">'+n.type+'</span>'
        +' &nbsp;·&nbsp; depth '+n.depth
        +' &nbsp;·&nbsp; '+n.runs+' run'+(n.runs!==1?'s':''));
    if(!ghost){{
      var links2=allEdges.filter(function(e2){{return e2.kind==='link'&&(e2.source===n.id||e2.target===n.id);}}).length;
      var tags2=allEdges.filter(function(e2){{return e2.kind==='tag'&&(e2.source===n.id||e2.target===n.id);}}).length;
      info.innerHTML='<strong style="color:#ccc">'+n.name+'</strong>'
        +' &nbsp;<span style="color:#333">·</span>&nbsp; '
        +'<span style="color:rgb('+cr+','+cg+','+cb+')">'+n.type+'</span>'
        +' &nbsp; depth <span style="color:var(--accent)">'+n.depth+'</span>'
        +' &nbsp; '+n.runs+' run'+(n.runs!==1?'s':'')
        +' &nbsp; '+links2+' link'+(links2!==1?'s':'')
        +' &nbsp; '+tags2+' shared tag'+(tags2!==1?'s':'')
        +' &nbsp;&nbsp;<a href="/vault/'+n.id+'">Open →</a>'
        +' &nbsp;<span style="color:#333">(dbl-click)</span>';
    }}else{{
      info.innerHTML='<span style="color:#446677">'+n.name+'</span>'
        +' &nbsp;<span style="color:#333">·</span>&nbsp; referenced but not yet researched';
    }}
  }}else{{
    canvas.style.cursor=panning?'grabbing':'default';
    tooltip.style.display='none';
  }}
}});

canvas.addEventListener('mouseup',function(){{dragNode=null;panning=false;canvas.style.cursor='default';}});
canvas.addEventListener('mouseleave',function(){{hoveredId=null;dragNode=null;panning=false;tooltip.style.display='none';}});

canvas.addEventListener('click',function(e){{
  if(_wasDrag){{_wasDrag=false;return;}}
  var rect=canvas.getBoundingClientRect();
  var n=nodeAt(e.clientX-rect.left,e.clientY-rect.top);
  /* click empty space = deselect; click node already handled on mousedown */
  if(!n)selectedId=null;
}});

canvas.addEventListener('dblclick',function(e){{
  var rect=canvas.getBoundingClientRect();
  var n=nodeAt(e.clientX-rect.left,e.clientY-rect.top);
  if(n&&!n.ghost)window.location.href='/vault/'+n.id;
}});

}})();
</script>"""
    return _page("Research Graph", body, "graph")


# ── Entry ──────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("\n  Phantom Web UI  →  http://127.0.0.1:7777\n")
    uvicorn.run(app, host="127.0.0.1", port=7777, log_level="warning")
