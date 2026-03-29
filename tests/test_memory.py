"""Tests for memory.py — WAL mode, FTS search, sources table."""
import sqlite3
import pytest
from memory import MemoryStore


def test_wal_mode_enabled(tmp_memory):
    """SQLite WAL journal mode must be active."""
    conn = sqlite3.connect(tmp_memory._db_path)
    mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
    conn.close()
    assert mode == "wal"


def test_save_and_search_fact(tmp_memory):
    tmp_memory.save_fact("Python asyncio is the standard async library", tags="python,async")
    results = tmp_memory.search_facts("asyncio")
    assert len(results) >= 1
    assert "asyncio" in results[0]["content"]


def test_fts_tags_searchable(tmp_memory):
    tmp_memory.save_fact("Some fact about tokio", tags="rust,tokio,async")
    results = tmp_memory.search_facts("tokio")
    assert len(results) >= 1


def test_delete_fact(tmp_memory):
    fid = tmp_memory.save_fact("Temporary fact")
    assert tmp_memory.delete_fact(fid) is True
    assert tmp_memory.delete_fact(fid) is False


def test_total_facts(tmp_memory):
    assert tmp_memory.total_facts() == 0
    tmp_memory.save_fact("fact one")
    tmp_memory.save_fact("fact two")
    assert tmp_memory.total_facts() == 2


def test_record_source(tmp_memory):
    tmp_memory.record_source("https://example.com/article", topic_slug="ai-research")
    sources = tmp_memory.get_sources_for_topic("ai-research")
    assert len(sources) == 1
    assert sources[0]["url"] == "https://example.com/article"
    assert sources[0]["domain"] == "example.com"


def test_source_deduplication(tmp_memory):
    """Same URL recorded twice → fetch_count incremented, not a new row."""
    url = "https://example.com/page"
    tmp_memory.record_source(url, topic_slug="topic-a")
    tmp_memory.record_source(url, topic_slug="topic-a")
    sources = tmp_memory.get_sources_for_topic("topic-a")
    assert len(sources) == 1
    assert sources[0]["fetch_count"] == 2


def test_total_sources(tmp_memory):
    assert tmp_memory.total_sources() == 0
    tmp_memory.record_source("https://a.com")
    tmp_memory.record_source("https://b.com")
    assert tmp_memory.total_sources() == 2


def test_session_messages(tmp_memory):
    tmp_memory.add_message("user", "hello")
    tmp_memory.add_message("assistant", "world")
    msgs = tmp_memory.get_messages()
    assert len(msgs) == 2
    assert msgs[0]["role"] == "user"


def test_clear_session(tmp_memory):
    tmp_memory.add_message("user", "hello")
    tmp_memory.clear_session()
    assert tmp_memory.message_count() == 0


def test_build_memory_context_empty_query(tmp_memory):
    result = tmp_memory.build_memory_context("")
    assert result == ""


def test_multiple_instances_same_db(tmp_path):
    """Two MemoryStore instances on the same DB — both can write (WAL)."""
    db_path = str(tmp_path / "data" / "shared.db")
    store1 = MemoryStore(db_path)
    store2 = MemoryStore(db_path)
    store1.save_fact("fact from store 1")
    store2.save_fact("fact from store 2")
    assert store1.total_facts() == 2
    store1.close()
    store2.close()
