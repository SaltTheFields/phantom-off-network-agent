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
                PRAGMA foreign_keys = ON;
            """)
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

                CREATE TABLE IF NOT EXISTS memory_embeddings (
                    memory_id   INTEGER PRIMARY KEY REFERENCES memories(id) ON DELETE CASCADE,
                    model       TEXT DEFAULT '',
                    embedding   BLOB NOT NULL
                );

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

                CREATE TABLE IF NOT EXISTS note_history (
                    id           INTEGER PRIMARY KEY AUTOINCREMENT,
                    slug         TEXT NOT NULL,
                    body         TEXT NOT NULL,
                    depth        INTEGER DEFAULT 0,
                    word_count   INTEGER DEFAULT 0,
                    saved_at     TEXT DEFAULT (datetime('now')),
                    run_number   INTEGER DEFAULT 0
                );
                CREATE INDEX IF NOT EXISTS note_history_slug ON note_history(slug, saved_at DESC);
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

            # Store vector embedding if sentence-transformers is available
            try:
                from embeddings import is_available, embed, store_embedding
                if is_available():
                    vec = embed(content.strip())
                    store_embedding(conn, last_id, vec)
            except Exception:
                pass  # Embeddings are optional — never crash on this

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

    def semantic_search(self, query: str, limit: int = None) -> list[dict]:
        """
        Search memories by semantic similarity using vector embeddings.
        Falls back to empty list if sentence-transformers not installed.
        """
        from embeddings import is_available, semantic_search as _sem_search
        if not is_available():
            return []
        n = limit or cfg.get("memory.max_long_term_results", 5)
        with self._lock:
            conn = self._get_conn()
            matches = _sem_search(conn, query, limit=n)
            if not matches:
                conn.close()
                return []
            ids = [m[0] for m in matches]
            score_map = {m[0]: m[1] for m in matches}
            placeholders = ",".join("?" * len(ids))
            cur = conn.cursor()
            cur.execute(
                f"SELECT id, content, tags, created_at, source_url FROM memories WHERE id IN ({placeholders})",
                ids,
            )
            rows = []
            for row in cur.fetchall():
                d = dict(row)
                d["semantic_score"] = round(score_map.get(d["id"], 0.0), 3)
                rows.append(d)
            conn.close()
            # Re-sort by semantic score
            rows.sort(key=lambda x: x["semantic_score"], reverse=True)
            return rows

    def hybrid_search(self, query: str, limit: int = None) -> list[dict]:
        """
        Hybrid search: merge FTS5 keyword results + semantic vector results.
        Deduplicates by id. Semantic results boosted when available.
        """
        n = limit or cfg.get("memory.max_long_term_results", 5)
        keyword_results = self.search_facts(query, limit=n * 2)
        semantic_results = self.semantic_search(query, limit=n * 2)

        # Merge by id, semantic takes priority
        seen: dict[int, dict] = {}
        for r in semantic_results:
            seen[r["id"]] = r
        for r in keyword_results:
            if r["id"] not in seen:
                r.setdefault("semantic_score", 0.0)
                seen[r["id"]] = r

        merged = sorted(seen.values(), key=lambda x: x.get("semantic_score", 0.0), reverse=True)
        return merged[:n]

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
        results = self.hybrid_search(query)
        if not results:
            return ""
        lines = ["Relevant memories from past sessions:"]
        for r in results:
            date = r["created_at"][:10] if r["created_at"] else "?"
            sem = f" [sim:{r['semantic_score']:.2f}]" if r.get("semantic_score") else ""
            line = f"  [{r['id']}] ({date}){sem} {r['content']}"
            if r.get("source_url"):
                line += f" [src: {r['source_url']}]"
            lines.append(line)
        return "\n".join(lines)

    # ── Source registry ───────────────────────────────────────────────────────

    def record_source(self, url: str, title: str = "", topic_slug: str = "",
                      reliability: int = None) -> int:
        from urllib.parse import urlparse
        domain = urlparse(url).netloc
        # Auto-score if not provided
        if reliability is None:
            try:
                from tools import score_domain
                reliability, _ = score_domain(url)
            except Exception:
                reliability = 3
        with self._lock:
            conn = self._get_conn()
            cur = conn.cursor()
            cur.execute(
                """
                INSERT INTO sources (url, domain, title, topic_slug, session_id, reliability)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(url) DO UPDATE SET
                    last_fetched = datetime('now'),
                    fetch_count = fetch_count + 1,
                    title = CASE WHEN excluded.title != '' THEN excluded.title ELSE title END,
                    topic_slug = CASE WHEN excluded.topic_slug != '' THEN excluded.topic_slug ELSE topic_slug END
                """,
                (url.strip(), domain, title.strip(), topic_slug.strip(),
                 self._session_id, reliability),
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

    # ── Note history ──────────────────────────────────────────────────────────

    def save_note_snapshot(self, slug: str, body: str, depth: int = 0) -> int:
        """Save a snapshot of a note body before it gets overwritten."""
        word_count = len(body.split()) if body else 0
        with self._lock:
            conn = self._get_conn()
            cur = conn.cursor()
            # run_number = how many snapshots exist for this slug already + 1
            cur.execute("SELECT COUNT(*) FROM note_history WHERE slug = ?", (slug,))
            run_number = (cur.fetchone()[0] or 0) + 1
            cur.execute(
                "INSERT INTO note_history (slug, body, depth, word_count, run_number) VALUES (?, ?, ?, ?, ?)",
                (slug, body, depth, word_count, run_number),
            )
            conn.commit()
            last_id = cur.lastrowid
            conn.close()
            return last_id

    def get_note_history(self, slug: str, limit: int = 20) -> list[dict]:
        """Return snapshots for a slug, newest first."""
        with self._lock:
            conn = self._get_conn()
            cur = conn.cursor()
            cur.execute(
                "SELECT id, slug, body, depth, word_count, saved_at, run_number "
                "FROM note_history WHERE slug = ? ORDER BY saved_at DESC LIMIT ?",
                (slug, limit),
            )
            rows = [dict(r) for r in cur.fetchall()]
            conn.close()
            return rows

    def get_note_snapshot_count(self, slug: str) -> int:
        with self._lock:
            conn = self._get_conn()
            cur = conn.cursor()
            cur.execute("SELECT COUNT(*) FROM note_history WHERE slug = ?", (slug,))
            count = cur.fetchone()[0]
            conn.close()
            return count

    def close(self):
        # connections are closed per-call now
        pass
