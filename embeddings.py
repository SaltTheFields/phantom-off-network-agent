"""
Local vector embeddings for semantic memory search.

Uses sentence-transformers (all-MiniLM-L6-v2 by default — 80MB, CPU-friendly).
Falls back gracefully to keyword-only search if the package isn't installed.

The embeddings table stores a float32 blob per memory row.
On search: cosine similarity between query embedding and all stored embeddings,
combined with FTS5 BM25 score for a hybrid result.
"""

import os
import struct
import sqlite3
import threading
from typing import Optional

_MODEL_NAME = "all-MiniLM-L6-v2"
_model = None
_model_lock = threading.Lock()
_available: Optional[bool] = None   # None = not yet checked


def is_available() -> bool:
    """Return True if sentence-transformers is installed."""
    global _available
    if _available is not None:
        return _available
    try:
        import sentence_transformers  # noqa: F401
        _available = True
    except ImportError:
        _available = False
    return _available


def get_model():
    """Lazy-load the embedding model (thread-safe, loaded once)."""
    global _model
    if _model is not None:
        return _model
    with _model_lock:
        if _model is None:
            import logging
            import warnings
            # Suppress noisy HF hub and transformers load messages
            os.environ.setdefault("HF_HUB_DISABLE_IMPLICIT_TOKEN", "1")
            os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")
            logging.getLogger("sentence_transformers").setLevel(logging.ERROR)
            logging.getLogger("transformers").setLevel(logging.ERROR)
            logging.getLogger("huggingface_hub").setLevel(logging.ERROR)
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                from sentence_transformers import SentenceTransformer
                _model = SentenceTransformer(_MODEL_NAME, device="cpu")
    return _model


def embed(text: str) -> list[float]:
    """Return a float32 embedding vector for text. Raises if unavailable."""
    model = get_model()
    vec = model.encode(text, normalize_embeddings=True)
    return vec.tolist()


def encode_blob(vec: list[float]) -> bytes:
    """Pack float list to bytes for SQLite storage."""
    return struct.pack(f"{len(vec)}f", *vec)


def decode_blob(blob: bytes) -> list[float]:
    """Unpack bytes from SQLite to float list."""
    n = len(blob) // 4
    return list(struct.unpack(f"{n}f", blob))


def cosine_similarity(a: list[float], b: list[float]) -> float:
    """Cosine similarity — vectors assumed unit-normalized (from SentenceTransformer)."""
    dot = sum(x * y for x, y in zip(a, b))
    # Clamp to [-1, 1] for safety
    return max(-1.0, min(1.0, dot))


# ── SQLite schema helpers ─────────────────────────────────────────────────────

EMBEDDINGS_TABLE_SQL = """
    CREATE TABLE IF NOT EXISTS memory_embeddings (
        memory_id   INTEGER PRIMARY KEY REFERENCES memories(id) ON DELETE CASCADE,
        model       TEXT DEFAULT '',
        embedding   BLOB NOT NULL
    );
"""


def ensure_embeddings_table(conn: sqlite3.Connection) -> None:
    conn.execute(EMBEDDINGS_TABLE_SQL)
    conn.commit()


def store_embedding(conn: sqlite3.Connection, memory_id: int, vec: list[float]) -> None:
    blob = encode_blob(vec)
    conn.execute(
        """
        INSERT INTO memory_embeddings (memory_id, model, embedding)
        VALUES (?, ?, ?)
        ON CONFLICT(memory_id) DO UPDATE SET embedding = excluded.embedding
        """,
        (memory_id, _MODEL_NAME, blob),
    )
    conn.commit()


def semantic_search(
    conn: sqlite3.Connection,
    query: str,
    limit: int = 5,
    threshold: float = 0.25,
) -> list[tuple[int, float]]:
    """
    Search memory_embeddings for rows semantically similar to query.
    Returns list of (memory_id, similarity_score) sorted by score desc.
    Only returns results above threshold.
    """
    if not is_available():
        return []

    try:
        q_vec = embed(query)
    except Exception:
        return []

    cur = conn.execute(
        "SELECT memory_id, embedding FROM memory_embeddings"
    )
    rows = cur.fetchall()
    if not rows:
        return []

    scored = []
    for memory_id, blob in rows:
        try:
            vec = decode_blob(blob)
            sim = cosine_similarity(q_vec, vec)
            if sim >= threshold:
                scored.append((memory_id, sim))
        except Exception:
            continue

    scored.sort(key=lambda x: x[1], reverse=True)
    return scored[:limit]
