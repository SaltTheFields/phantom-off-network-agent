"""
Article cache for Phantom Off-Network Agent.

Stores fetched web pages in SQLite with timestamps so the agent can:
  - Skip re-fetching recent content (configurable TTL)
  - Detect content changes (diff on re-fetch)
  - Track which URLs have been visited and when
"""
import hashlib
import os
import sqlite3
import threading
from datetime import datetime, timedelta

from config import cfg

_DB_PATH = "data/article_cache.db"
_lock = threading.Lock()
_conn: sqlite3.Connection | None = None


def _get_conn() -> sqlite3.Connection:
    global _conn
    if _conn is None:
        os.makedirs("data", exist_ok=True)
        _conn = sqlite3.connect(_DB_PATH, check_same_thread=False)
        _conn.execute("PRAGMA journal_mode=WAL")
        _conn.execute("""
            CREATE TABLE IF NOT EXISTS article_cache (
                url          TEXT PRIMARY KEY,
                fetched_at   TEXT NOT NULL,
                content_hash TEXT NOT NULL,
                content      TEXT NOT NULL,
                changed      INTEGER DEFAULT 0,
                fetch_count  INTEGER DEFAULT 1
            )
        """)
        _conn.commit()
    return _conn


def _hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8", errors="replace")).hexdigest()[:16]


def get_cached(url: str, max_age_hours: float = None) -> dict | None:
    """
    Return cached entry for url if it exists and is fresh enough.
    Returns None if not cached or stale.
    dict keys: url, fetched_at, content, content_hash, changed, fetch_count
    """
    if max_age_hours is None:
        max_age_hours = cfg.get("search.cache_max_age_hours", 24.0)
    with _lock:
        try:
            conn = _get_conn()
            row = conn.execute(
                "SELECT url, fetched_at, content_hash, content, changed, fetch_count "
                "FROM article_cache WHERE url = ?", (url,)
            ).fetchone()
            if not row:
                return None
            fetched_at = datetime.fromisoformat(row[1])
            if datetime.now() - fetched_at > timedelta(hours=max_age_hours):
                return None  # stale
            return {
                "url": row[0], "fetched_at": row[1],
                "content_hash": row[2], "content": row[3],
                "changed": bool(row[4]), "fetch_count": row[5],
            }
        except Exception:
            return None


def save_cache(url: str, content: str) -> dict:
    """
    Upsert cache entry. Returns a dict with:
      changed: True if content differs from previous fetch
      diff_summary: short human-readable summary of what changed
      fetch_count: how many times this URL has been fetched
    """
    h = _hash(content)
    now = datetime.now().isoformat(timespec="seconds")
    changed = False
    diff_summary = ""
    fetch_count = 1

    with _lock:
        try:
            conn = _get_conn()
            existing = conn.execute(
                "SELECT content_hash, content, fetch_count FROM article_cache WHERE url = ?", (url,)
            ).fetchone()

            if existing:
                old_hash, old_content, fetch_count = existing
                fetch_count += 1
                changed = (old_hash != h)
                if changed:
                    diff_summary = _diff_summary(old_content, content)
                conn.execute(
                    "UPDATE article_cache SET fetched_at=?, content_hash=?, content=?, "
                    "changed=?, fetch_count=? WHERE url=?",
                    (now, h, content, int(changed), fetch_count, url)
                )
            else:
                conn.execute(
                    "INSERT INTO article_cache (url, fetched_at, content_hash, content, changed, fetch_count) "
                    "VALUES (?, ?, ?, ?, 0, 1)",
                    (url, now, h, content)
                )
            conn.commit()
        except Exception:
            pass

    return {"changed": changed, "diff_summary": diff_summary, "fetch_count": fetch_count}


def _diff_summary(old: str, new: str, max_chars: int = 200) -> str:
    """Produce a short summary of lines added/removed between old and new content."""
    old_lines = set(l.strip() for l in old.splitlines() if l.strip())
    new_lines = set(l.strip() for l in new.splitlines() if l.strip())
    added   = new_lines - old_lines
    removed = old_lines - new_lines
    parts = []
    if added:
        sample = list(added)[:2]
        parts.append(f"+{len(added)} new lines (e.g. \"{sample[0][:60]}\")")
    if removed:
        sample = list(removed)[:2]
        parts.append(f"-{len(removed)} removed lines")
    if not parts:
        return "content reorganized (same lines, different order)"
    return "; ".join(parts)[:max_chars]


def recent_fetches(limit: int = 20) -> list[dict]:
    """Return most recently fetched URLs with metadata (no content body)."""
    with _lock:
        try:
            conn = _get_conn()
            rows = conn.execute(
                "SELECT url, fetched_at, content_hash, changed, fetch_count "
                "FROM article_cache ORDER BY fetched_at DESC LIMIT ?", (limit,)
            ).fetchall()
            return [
                {"url": r[0], "fetched_at": r[1], "hash": r[2],
                 "changed": bool(r[3]), "fetch_count": r[4]}
                for r in rows
            ]
        except Exception:
            return []


def cache_stats() -> dict:
    """Return total cached URLs and count of changed re-fetches."""
    with _lock:
        try:
            conn = _get_conn()
            total   = conn.execute("SELECT COUNT(*) FROM article_cache").fetchone()[0]
            changed = conn.execute("SELECT COUNT(*) FROM article_cache WHERE changed=1").fetchone()[0]
            return {"total": total, "changed": changed}
        except Exception:
            return {"total": 0, "changed": 0}
