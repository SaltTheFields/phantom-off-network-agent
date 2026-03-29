import sqlite3
import uuid
import os
import threading
from datetime import datetime
from config import cfg


class MemoryStore:
    def __init__(self, db_path: str = None):
        self._db_path = db_path or cfg.get("memory.db_path", "data/memory.db")
        os.makedirs(os.path.dirname(self._db_path), exist_ok=True)
        self._session_id = str(uuid.uuid4())[:8]
        self._messages: list[dict] = []
        self._lock = threading.RLock()
        self._init_db()

    def _get_conn(self):
        conn = sqlite3.connect(self._db_path, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self):
        with self._lock:
            conn = self._get_conn()
            conn.execute("PRAGMA journal_mode=WAL")
            cur = conn.cursor()
            cur.executescript("""
                CREATE TABLE IF NOT EXISTS memories (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    content     TEXT NOT NULL,
                    tags        TEXT DEFAULT '',
                    created_at  TEXT DEFAULT (datetime('now')),
                    session_id  TEXT DEFAULT '',
                    source_url  TEXT DEFAULT ''
                );

                CREATE VIRTUAL TABLE IF NOT EXISTS memories_fts
                    USING fts5(content, tags, content=memories, content_rowid=id);

                CREATE TRIGGER IF NOT EXISTS memories_ai
                    AFTER INSERT ON memories BEGIN
                        INSERT INTO memories_fts(rowid, content, tags)
                        VALUES (new.id, new.content, new.tags);
                    END;

                CREATE TRIGGER IF NOT EXISTS memories_ad
                    AFTER DELETE ON memories BEGIN
                        INSERT INTO memories_fts(memories_fts, rowid, content, tags)
                        VALUES ('delete', old.id, old.content, old.tags);
                    END;

                CREATE TABLE IF NOT EXISTS sources (
                    id            INTEGER PRIMARY KEY AUTOINCREMENT,
                    url           TEXT NOT NULL UNIQUE,
                    domain        TEXT DEFAULT '',
                    title         TEXT DEFAULT '',
                    first_fetched TEXT DEFAULT (datetime('now')),
                    last_fetched  TEXT DEFAULT (datetime('now')),
                    fetch_count   INTEGER DEFAULT 1,
                    topic_slug    TEXT DEFAULT '',
                    session_id    TEXT DEFAULT '',
                    reliability   INTEGER DEFAULT 3
                );
            """)
            conn.commit()
            conn.close()

    # ── Short-term (in-memory, session only) ──────────────────────────────

    def add_message(self, role: str, content: str) -> None:
        self._messages.append({"role": role, "content": content})

    def get_messages(self) -> list[dict]:
        return list(self._messages)

    def trim_history(self, max_messages: int = None) -> None:
        limit = max_messages or cfg.get("memory.max_short_term_messages", 20)
        if len(self._messages) > limit:
            # Always keep at least the first message for session context
            self._messages = self._messages[:1] + self._messages[-(limit - 1):]

    def clear_session(self) -> None:
        self._messages = []

    def message_count(self) -> int:
        return len(self._messages)

    # ── Long-term (SQLite FTS5) ────────────────────────────────────────────

    def save_fact(self, content: str, tags: str = "", source_url: str = "") -> int:
        with self._lock:
            conn = self._get_conn()
            cur = conn.cursor()
            cur.execute(
                "INSERT INTO memories (content, tags, session_id, source_url) VALUES (?, ?, ?, ?)",
                (content.strip(), tags.strip(), self._session_id, source_url.strip()),
            )
            conn.commit()
            last_id = cur.lastrowid
            conn.close()
            return last_id

    def search_facts(self, query: str, limit: int = None) -> list[dict]:
        n = limit or cfg.get("memory.max_long_term_results", 5)
        with self._lock:
            conn = self._get_conn()
            cur = conn.cursor()
            try:
                cur.execute(
                    """
                    SELECT m.id, m.content, m.tags, m.created_at, m.source_url
                    FROM memories_fts f
                    JOIN memories m ON m.id = f.rowid
                    WHERE memories_fts MATCH ?
                    ORDER BY rank
                    LIMIT ?
                    """,
                    (query, n),
                )
                rows = [dict(row) for row in cur.fetchall()]
            except sqlite3.OperationalError:
                # FTS fallback: simple LIKE search
                terms = query.split()
                like_clause = " OR ".join(["content LIKE ? OR tags LIKE ?"] * len(terms))
                params = [f"%{t}%" for t in terms for _ in range(2)]
                cur.execute(
                    f"SELECT id, content, tags, created_at, source_url FROM memories WHERE {like_clause} LIMIT ?",
                    params + [n],
                )
                rows = [dict(row) for row in cur.fetchall()]
            conn.close()
            return rows

    def get_recent_facts(self, limit: int = 10) -> list[dict]:
        with self._lock:
            conn = self._get_conn()
            cur = conn.cursor()
            cur.execute(
                "SELECT id, content, tags, created_at, source_url FROM memories ORDER BY id DESC LIMIT ?",
                (limit,),
            )
            rows = [dict(row) for row in cur.fetchall()]
            conn.close()
            return rows

    def delete_fact(self, fact_id: int) -> bool:
        with self._lock:
            conn = self._get_conn()
            cur = conn.cursor()
            cur.execute("DELETE FROM memories WHERE id = ?", (fact_id,))
            conn.commit()
            count = cur.rowcount
            conn.close()
            return count > 0

    def total_facts(self) -> int:
        with self._lock:
            conn = self._get_conn()
            cur = conn.cursor()
            cur.execute("SELECT COUNT(*) FROM memories")
            total = cur.fetchone()[0]
            conn.close()
            return total

    def export_session_summary(self, summary: str) -> int:
        tags = f"session-summary,{self._session_id}"
        return self.save_fact(summary, tags=tags)

    def build_memory_context(self, query: str) -> str:
        if not query.strip():
            return ""
        results = self.search_facts(query)
        if not results:
            return ""
        lines = ["Relevant memories from past sessions:"]
        for r in results:
            date = r["created_at"][:10] if r["created_at"] else "?"
            line = f"  [{r['id']}] ({date}) {r['content']}"
            if r.get("source_url"):
                line += f" [src: {r['source_url']}]"
            lines.append(line)
        return "\n".join(lines)

    # ── Source registry ───────────────────────────────────────────────────────

    def record_source(self, url: str, title: str = "", topic_slug: str = "") -> int:
        from urllib.parse import urlparse
        domain = urlparse(url).netloc
        with self._lock:
            conn = self._get_conn()
            cur = conn.cursor()
            cur.execute(
                """
                INSERT INTO sources (url, domain, title, topic_slug, session_id)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(url) DO UPDATE SET
                    last_fetched = datetime('now'),
                    fetch_count = fetch_count + 1,
                    title = CASE WHEN excluded.title != '' THEN excluded.title ELSE title END,
                    topic_slug = CASE WHEN excluded.topic_slug != '' THEN excluded.topic_slug ELSE topic_slug END
                """,
                (url.strip(), domain, title.strip(), topic_slug.strip(), self._session_id),
            )
            conn.commit()
            last_id = cur.lastrowid or 0
            conn.close()
            return last_id

    def source_fetched_this_session(self, url: str) -> bool:
        with self._lock:
            conn = self._get_conn()
            cur = conn.cursor()
            cur.execute(
                "SELECT 1 FROM sources WHERE url = ? AND session_id = ?",
                (url.strip(), self._session_id),
            )
            fetched = cur.fetchone() is not None
            conn.close()
            return fetched

    def get_sources_for_topic(self, topic_slug: str) -> list[dict]:
        with self._lock:
            conn = self._get_conn()
            cur = conn.cursor()
            cur.execute(
                "SELECT * FROM sources WHERE topic_slug = ? ORDER BY last_fetched DESC",
                (topic_slug,),
            )
            rows = [dict(row) for row in cur.fetchall()]
            conn.close()
            return rows

    def total_sources(self) -> int:
        with self._lock:
            conn = self._get_conn()
            cur = conn.cursor()
            cur.execute("SELECT COUNT(*) FROM sources")
            total = cur.fetchone()[0]
            conn.close()
            return total

    def close(self):
        # connections are closed per-call now
        pass
