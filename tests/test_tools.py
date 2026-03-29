"""Tests for tools.py — execute_tool with all 6 tools."""
import pytest
from tools import execute_tool, web_search
from vault import Note


# ── web_search ────────────────────────────────────────────────────────────────

def test_web_search_missing_query(tmp_memory):
    result = execute_tool({"tool": "web_search"}, tmp_memory)
    assert "requires" in result.lower() or "error" in result.lower()


def test_web_search_offline(tmp_memory, monkeypatch):
    """DuckDuckGo unavailable → graceful failure message."""
    import tools
    monkeypatch.setattr(tools, "web_search", lambda q, max_results=None: f"Search failed: offline")
    result = execute_tool({"tool": "web_search", "query": "test"}, tmp_memory)
    assert "Search failed" in result or "failed" in result.lower()


# ── fetch_page ────────────────────────────────────────────────────────────────

def test_fetch_page_invalid_url(tmp_memory):
    result = execute_tool({"tool": "fetch_page", "url": "not-a-url"}, tmp_memory)
    assert "Invalid URL" in result or "http" in result.lower()


def test_fetch_page_missing_url(tmp_memory):
    result = execute_tool({"tool": "fetch_page"}, tmp_memory)
    assert "requires" in result.lower() or "error" in result.lower()


# ── remember / recall ─────────────────────────────────────────────────────────

def test_remember_and_recall(tmp_memory):
    result = execute_tool({"tool": "remember", "content": "tokio is async rust", "tags": "rust"}, tmp_memory)
    assert "Saved" in result

    result = execute_tool({"tool": "recall", "query": "tokio"}, tmp_memory)
    assert "tokio" in result.lower()


def test_recall_no_results(tmp_memory):
    result = execute_tool({"tool": "recall", "query": "xyznonexistent"}, tmp_memory)
    assert "No memories" in result or "no memories" in result.lower()


def test_remember_missing_content(tmp_memory):
    result = execute_tool({"tool": "remember"}, tmp_memory)
    assert "requires" in result.lower() or "error" in result.lower()


# ── read_note ─────────────────────────────────────────────────────────────────

def test_read_note_found(tmp_memory, tmp_vault, sample_topic):
    from topics import TopicManager
    topics = TopicManager(tmp_vault)
    result = execute_tool({"tool": "read_note", "topic": "AI Research"}, tmp_memory, vault=tmp_vault, topics=topics)
    assert "AI Research" in result
    assert "Status" in result


def test_read_note_not_found(tmp_memory, tmp_vault):
    result = execute_tool({"tool": "read_note", "topic": "Nonexistent Topic"}, tmp_memory, vault=tmp_vault)
    assert "No note found" in result or "not found" in result.lower()


def test_read_note_no_vault(tmp_memory):
    result = execute_tool({"tool": "read_note", "topic": "Test"}, tmp_memory, vault=None)
    assert "not available" in result.lower()


# ── update_note ───────────────────────────────────────────────────────────────

def test_update_note(tmp_memory, tmp_vault, sample_topic):
    from topics import TopicManager
    topics = TopicManager(tmp_vault)
    result = execute_tool(
        {"tool": "update_note", "topic": "AI Research", "body": "# AI Research\n\nUpdated content."},
        tmp_memory, vault=tmp_vault, topics=topics,
    )
    assert "updated" in result.lower() or "Note updated" in result

    note = tmp_vault.read_note(sample_topic.slug)
    assert "Updated content" in note.body


def test_update_note_auto_creates(tmp_memory, tmp_vault):
    """update_note auto-creates the note if it doesn't exist yet."""
    result = execute_tool(
        {"tool": "update_note", "topic": "Brand New Topic", "body": "# Brand New Topic\n\nContent."},
        tmp_memory, vault=tmp_vault,
    )
    assert "updated" in result.lower() or "Note updated" in result
    assert tmp_vault.note_exists("brand-new-topic")


def test_update_note_records_source(tmp_memory, tmp_vault, sample_topic):
    execute_tool(
        {
            "tool": "update_note",
            "topic": "AI Research",
            "body": "# AI Research\n\nContent.",
            "sources": "https://example.com/src",
        },
        tmp_memory, vault=tmp_vault,
    )
    sources = tmp_memory.get_sources_for_topic(sample_topic.slug)
    assert any(s["url"] == "https://example.com/src" for s in sources)


def test_unknown_tool(tmp_memory):
    result = execute_tool({"tool": "fly_to_moon"}, tmp_memory)
    assert "Unknown tool" in result
