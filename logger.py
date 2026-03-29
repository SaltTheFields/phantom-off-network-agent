"""
Structured run logger for Phantom Off-Network Agent.
Writes JSONL entries to logs/phantom-YYYY-MM-DD.log, one file per day (appended).
Never crashes the agent — all writes are wrapped in try/except.
"""
import json
import os
import time
from datetime import datetime, date, timedelta

from config import cfg


class PhantomLogger:
    def __init__(self, on_event=None):
        self._enabled = cfg.get("logging.enabled", True)
        self._log_dir = cfg.get("logging.log_dir", "logs")
        self._level = cfg.get("logging.level", "INFO")
        self._fh = None
        self._run_start_ts = None
        self._on_event = on_event  # optional callback(data: dict) for live streaming

        if not self._enabled:
            return

        try:
            os.makedirs(self._log_dir, exist_ok=True)
            self._rotate_old_logs()
            log_path = self._log_path()
            self._fh = open(log_path, "a", encoding="utf-8", buffering=1)
        except Exception:
            self._enabled = False

    # ── Internal helpers ──────────────────────────────────────────────────────

    def _log_path(self) -> str:
        return os.path.join(self._log_dir, f"phantom-{date.today()}.log")

    def _rotate_old_logs(self):
        max_age = cfg.get("logging.max_log_age_days", 30)
        cutoff = date.today() - timedelta(days=max_age)
        try:
            for fname in os.listdir(self._log_dir):
                if not fname.startswith("phantom-") or not fname.endswith(".log"):
                    continue
                # parse date from phantom-YYYY-MM-DD.log
                date_str = fname[8:18]
                try:
                    file_date = datetime.strptime(date_str, "%Y-%m-%d").date()
                    if file_date < cutoff:
                        os.remove(os.path.join(self._log_dir, fname))
                except ValueError:
                    pass
        except Exception:
            pass

    def _ts(self) -> str:
        return datetime.now().isoformat(timespec="seconds")

    def _write(self, data: dict):
        if not self._enabled or self._fh is None:
            return
        try:
            self._fh.write(json.dumps(data) + "\n")
        except Exception:
            pass
        if self._on_event:
            try:
                self._on_event(data)
            except Exception:
                pass

    def _header(self, lines: list[str]):
        if not self._enabled or self._fh is None:
            return
        try:
            sep = "=" * 80
            self._fh.write(sep + "\n")
            for line in lines:
                self._fh.write(line + "\n")
            self._fh.write(sep + "\n")
        except Exception:
            pass

    # ── Public API ────────────────────────────────────────────────────────────

    def run_start(self, mode: str, model: str, queue_size: int):
        self._run_start_ts = time.time()
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        workers = cfg.get("schedule.max_parallel_workers", 1)
        self._header([
            f"PHANTOM RUN — {now}",
            f"Mode: {mode} | Model: {model} | Topics queued: {queue_size} | Workers: {workers}",
        ])
        self._write({
            "ts": self._ts(), "level": "INFO", "event": "run_start",
            "mode": mode, "model": model, "queue_size": queue_size,
        })

    def topic_start(self, note, position: int, total: int):
        self._write({
            "ts": self._ts(), "level": "INFO", "event": "topic_start",
            "topic": note.name, "slug": note.slug,
            "priority": note.priority, "type": note.type,
            "position": position, "of": total,
        })

    def tool_call(self, tool_name: str, topic_slug: str = "", **kwargs):
        entry = {"ts": self._ts(), "level": "INFO", "event": "tool_call",
                 "tool": tool_name, "topic": topic_slug}
        entry.update(kwargs)
        self._write(entry)

    def tool_result(self, tool_name: str, elapsed_ms: int, topic_slug: str = "", **kwargs):
        entry = {"ts": self._ts(), "level": "INFO", "event": "tool_result",
                 "tool": tool_name, "elapsed_ms": elapsed_ms, "topic": topic_slug}
        entry.update(kwargs)
        self._write(entry)

    def memory_saved(self, memory_id: int, topic_slug: str = ""):
        self._write({
            "ts": self._ts(), "level": "INFO", "event": "memory_saved",
            "memory_id": memory_id, "topic": topic_slug,
        })

    def note_written(self, slug: str, sources_count: int):
        self._write({
            "ts": self._ts(), "level": "INFO", "event": "note_written",
            "slug": slug, "sources": sources_count,
        })

    def topic_done(self, note, elapsed_s: float, sources: int, memories: int, iterations: int):
        self._write({
            "ts": self._ts(), "level": "INFO", "event": "topic_done",
            "topic": note.name, "slug": note.slug,
            "elapsed_s": round(elapsed_s, 1),
            "sources": sources, "memories": memories, "iterations": iterations,
        })

    def topic_failed(self, note, error: str, traceback_str: str = ""):
        self._write({
            "ts": self._ts(), "level": "ERROR", "event": "topic_failed",
            "topic": note.name, "slug": note.slug,
            "error": error, "traceback": traceback_str,
        })

    def warn(self, event: str, **kwargs):
        entry = {"ts": self._ts(), "level": "WARN", "event": event}
        entry.update(kwargs)
        self._write(entry)

    def run_done(self, completed: int, failed: int, total_elapsed_s: float):
        avg = round(total_elapsed_s / completed, 1) if completed else 0
        self._write({
            "ts": self._ts(), "level": "INFO", "event": "run_done",
            "topics_completed": completed, "topics_failed": failed,
            "total_elapsed_s": round(total_elapsed_s, 1),
            "avg_per_topic_s": avg,
        })

    def close(self):
        try:
            if self._fh:
                self._fh.close()
                self._fh = None
        except Exception:
            pass
