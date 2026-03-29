"""Tests for /topic import and /topic export (Tasks 3 & 5)."""
import json
import os
import pytest
from topics import TopicManager


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture
def topics(tmp_vault):
    return TopicManager(tmp_vault)


def write_txt(tmp_path, lines: list[str]) -> str:
    p = tmp_path / "import.txt"
    p.write_text("\n".join(lines), encoding="utf-8")
    return str(p)


def write_json(tmp_path, data: list) -> str:
    p = tmp_path / "import.json"
    p.write_text(json.dumps(data), encoding="utf-8")
    return str(p)


# ── parse_import_file ─────────────────────────────────────────────────────────

def test_parse_txt_basic(topics, tmp_path):
    path = write_txt(tmp_path, [
        "AI Research | tech | high | ai, ml | 14",
        "Quantum Computing | tech | medium | qc | 7",
    ])
    rows, errors = topics.parse_import_file(path)
    assert len(rows) == 2
    assert errors == []
    assert rows[0]["name"] == "AI Research"
    assert rows[0]["type"] == "tech"
    assert rows[0]["priority"] == "high"
    assert rows[0]["refresh_interval_days"] == 14
    assert "ai" in rows[0]["tags"]


def test_parse_txt_defaults(topics, tmp_path):
    """Minimal line — only name, rest defaults."""
    path = write_txt(tmp_path, ["Minimal Topic"])
    rows, errors = topics.parse_import_file(path)
    assert len(rows) == 1
    assert rows[0]["type"] == "research"
    assert rows[0]["priority"] == "medium"


def test_parse_txt_comments_ignored(topics, tmp_path):
    path = write_txt(tmp_path, [
        "# This is a comment",
        "",
        "Real Topic | tech | high",
    ])
    rows, errors = topics.parse_import_file(path)
    assert len(rows) == 1
    assert rows[0]["name"] == "Real Topic"


def test_parse_json_basic(topics, tmp_path):
    data = [
        {"name": "AI Safety", "type": "tech", "priority": "high", "tags": ["ai"], "refresh_interval_days": 21},
        {"name": "Robotics", "type": "tech", "priority": "medium"},
    ]
    path = write_json(tmp_path, data)
    rows, errors = topics.parse_import_file(path)
    assert len(rows) == 2
    assert errors == []
    assert rows[0]["name"] == "AI Safety"
    assert rows[0]["refresh_interval_days"] == 21


def test_parse_invalid_type_gives_error(topics, tmp_path):
    path = write_txt(tmp_path, ["Bad Topic | invalidtype | high"])
    rows, errors = topics.parse_import_file(path)
    assert len(rows) == 0
    assert len(errors) == 1
    assert "invalidtype" in errors[0]


def test_parse_invalid_priority_gives_error(topics, tmp_path):
    path = write_txt(tmp_path, ["Bad Topic | tech | critical"])
    rows, errors = topics.parse_import_file(path)
    assert len(rows) == 0
    assert "critical" in errors[0]


def test_parse_file_not_found(topics):
    rows, errors = topics.parse_import_file("/nonexistent/file.txt")
    assert rows == []
    assert "not found" in errors[0].lower()


def test_parse_json_not_array(topics, tmp_path):
    p = tmp_path / "bad.json"
    p.write_text('{"name": "single object"}', encoding="utf-8")
    rows, errors = topics.parse_import_file(str(p))
    assert rows == []
    assert "array" in errors[0].lower()


# ── import_topics (with monkeypatched input) ──────────────────────────────────

def test_import_creates_topics(topics, tmp_path, monkeypatch):
    path = write_txt(tmp_path, [
        "Stage Magic | concept | high | magic | 14",
        "Reginald Scot | person | high | history | 30",
    ])
    monkeypatch.setattr("builtins.input", lambda _: "y")
    result = topics.import_topics(path)
    assert "Created: 2" in result
    assert topics.get_topic("Stage Magic") is not None
    assert topics.get_topic("Reginald Scot") is not None


def test_import_skips_existing(topics, tmp_path, monkeypatch):
    topics.create_topic("Existing Topic", type="tech")
    path = write_txt(tmp_path, [
        "Existing Topic | tech | high",
        "New Topic | tech | medium",
    ])
    monkeypatch.setattr("builtins.input", lambda _: "y")
    result = topics.import_topics(path)
    assert "Skipped: 1" in result
    assert "Created: 1" in result


def test_import_cancelled(topics, tmp_path, monkeypatch):
    path = write_txt(tmp_path, ["New Topic | tech | high"])
    monkeypatch.setattr("builtins.input", lambda _: "n")
    result = topics.import_topics(path)
    assert "Cancelled" in result
    assert topics.get_topic("New Topic") is None


def test_import_all_exist_no_prompt(topics, tmp_path, monkeypatch):
    """All topics exist → no input() called."""
    topics.create_topic("Alpha")
    path = write_txt(tmp_path, ["Alpha"])
    called = []
    monkeypatch.setattr("builtins.input", lambda _: called.append(1) or "y")
    result = topics.import_topics(path)
    assert called == []
    assert "Nothing to create" in result


# ── export_topics ─────────────────────────────────────────────────────────────

def test_export_creates_file(topics, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    topics.create_topic("AI Research", type="tech", priority="high")
    topics.create_topic("History", type="research", priority="low")
    result = topics.export_topics()
    assert "Exported 2" in result
    # File was created
    from datetime import date
    fname = f"topic-export-{date.today()}.json"
    assert os.path.exists(tmp_path / fname)


def test_export_roundtrip(topics, tmp_path, monkeypatch):
    """Export then re-import produces same topics in a fresh vault."""
    monkeypatch.chdir(tmp_path)
    topics.create_topic("Alpha", type="tech", priority="high", tags=["a"], refresh_interval_days=14)
    topics.create_topic("Beta", type="concept", priority="low")

    result = topics.export_topics()
    from datetime import date
    fname = str(tmp_path / f"topic-export-{date.today()}.json")

    # Fresh vault
    from vault import VaultManager
    vault2 = VaultManager(str(tmp_path / "vault2"))
    topics2 = TopicManager(vault2)
    monkeypatch.setattr("builtins.input", lambda _: "y")
    import_result = topics2.import_topics(fname)
    assert "Created: 2" in import_result
    note = topics2.get_topic("Alpha")
    assert note.type == "tech"
    assert note.refresh_interval_days == 14


def test_export_status_filter(topics, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    topics.create_topic("Queued One")
    note = topics.create_topic("Active One")
    topics.update_status(note.slug, "active")

    result = topics.export_topics(status_filter="queued")
    assert "1 queued" in result

    from datetime import date
    fname = tmp_path / f"topic-export-queued-{date.today()}.json"
    with open(fname, encoding="utf-8") as f:
        data = json.load(f)
    assert len(data) == 1
    assert data[0]["name"] == "Queued One"


def test_export_empty(topics):
    result = topics.export_topics(status_filter="archived")
    assert "No" in result
