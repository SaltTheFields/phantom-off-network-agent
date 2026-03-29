"""Tests for agents.py — AgentRoster CRUD and model resolution."""
import json
import pytest
from agents import AgentRoster, AgentEntry


@pytest.fixture
def roster(tmp_path):
    return AgentRoster(path=str(tmp_path / "agents.json"))


def test_empty_roster_falls_back_to_config(roster):
    """No assignments → returns cfg.get('ollama.model')."""
    from config import cfg
    from vault import Note
    note = Note(slug="test", name="Test", type="tech")
    assert roster.get_model_for(note) == cfg.get("ollama.model")


def test_assign_type_persists(tmp_path):
    """assign_type() writes to agents.json."""
    path = str(tmp_path / "agents.json")
    r = AgentRoster(path=path)
    r.assign_type("mistral", "tech")

    with open(path) as f:
        data = json.load(f)
    assert any(a["model"] == "mistral" and "tech" in a["assigned_types"] for a in data["agents"])


def test_assign_topic_overrides_type(roster):
    """Topic-specific assignment beats type-level."""
    from vault import Note
    roster.assign_type("type-model", "tech")
    roster.assign_topic("topic-model", "ai-research")
    note = Note(slug="ai-research", name="AI Research", type="tech")
    assert roster.get_model_for(note) == "topic-model"


def test_clear_removes_entry(roster):
    """clear() removes model from roster."""
    roster.assign_type("mistral", "tech")
    assert roster.clear("mistral") is True
    assert roster.clear("mistral") is False  # already gone


def test_resolution_order(roster):
    """Resolution: slug > type > default_model > config fallback."""
    from vault import Note
    roster.assign_type("type-model", "tech")
    roster.set_default("default-model")

    # Type match
    note = Note(slug="some-slug", name="Some", type="tech")
    assert roster.get_model_for(note) == "type-model"

    # Default model when no type match
    note2 = Note(slug="other", name="Other", type="concept")
    assert roster.get_model_for(note2) == "default-model"

    # Slug beats type
    roster.assign_topic("slug-model", "some-slug")
    assert roster.get_model_for(note) == "slug-model"


def test_list_available_offline(roster, monkeypatch):
    """Ollama unreachable → assigned models shown as offline, no crash."""
    import llm
    def _fail(*a, **kw):
        from llm import OllamaConnectionError
        raise OllamaConnectionError("offline")
    monkeypatch.setattr(llm, "list_models", _fail)
    monkeypatch.setattr(llm, "get_loaded_models", lambda: [])

    roster.assign_type("mistral", "tech")
    rows = roster.list_available()
    assert any(r["model"] == "mistral" for r in rows)
    mistral_row = next(r for r in rows if r["model"] == "mistral")
    assert mistral_row["available"] is False
