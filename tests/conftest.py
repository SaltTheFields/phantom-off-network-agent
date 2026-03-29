"""
Shared fixtures for the Phantom Off-Network Agent test suite.
All fixtures use tmp_path so they never touch the real vault or DB.
"""
import sys
import os
import pytest

# Make project root importable
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from vault import VaultManager
from memory import MemoryStore
from topics import TopicManager


@pytest.fixture
def tmp_vault(tmp_path):
    """Fresh VaultManager in a temp directory."""
    return VaultManager(str(tmp_path / "vault"))


@pytest.fixture
def tmp_memory(tmp_path):
    """Fresh MemoryStore in a temp directory."""
    db_path = str(tmp_path / "data" / "memory.db")
    store = MemoryStore(db_path)
    yield store
    store.close()


@pytest.fixture
def sample_topic(tmp_vault):
    """Pre-created 'AI Research' tech topic in the temp vault."""
    topics = TopicManager(tmp_vault)
    note = topics.create_topic(
        "AI Research",
        type="tech",
        priority="high",
        tags=["ai", "machine-learning"],
    )
    return note


# Canned tool-call sequence used by mock_llm
_TOOL_SEQUENCE = [
    '```json\n{"tool": "read_note", "topic": "AI Research"}\n```',
    '```json\n{"tool": "web_search", "query": "AI research breakthroughs 2025"}\n```',
    (
        '```json\n{"tool": "update_note", "topic": "AI Research",'
        ' "body": "# AI Research\\n\\n## Summary\\nMock content about [[Large Language Models]].",'
        ' "sources": "https://example.com/ai-research"}\n```'
    ),
    "Research complete. I have updated the note with the latest findings.",
]


@pytest.fixture
def mock_llm(monkeypatch):
    """
    Stub llm.chat to return a pre-defined sequence of tool calls / final answer.
    Sequence: read_note → web_search → update_note → final answer
    """
    call_counter = {"n": 0}

    def _fake_chat(messages, system_prompt, stream=False, model=None):
        idx = call_counter["n"]
        call_counter["n"] += 1
        if idx < len(_TOOL_SEQUENCE):
            return _TOOL_SEQUENCE[idx]
        return "Research complete."

    import llm as llm_module
    monkeypatch.setattr(llm_module, "chat", _fake_chat)
    return _fake_chat
