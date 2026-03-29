"""Tests for logger.py — PhantomLogger structured run logging."""
import json
import os
import pytest
from datetime import date
from vault import Note


@pytest.fixture
def logger(tmp_path, monkeypatch):
    monkeypatch.setattr("config.cfg._data", {
        "logging": {"enabled": True, "log_dir": str(tmp_path / "logs"), "level": "INFO", "max_log_age_days": 30},
        "schedule": {"max_parallel_workers": 1},
    })
    from logger import PhantomLogger
    log = PhantomLogger()
    yield log
    log.close()


def _read_jsonl(path: str) -> list[dict]:
    events = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line.startswith("{"):
                events.append(json.loads(line))
    return events


def test_log_file_created(logger, tmp_path):
    log_path = tmp_path / "logs" / f"phantom-{date.today()}.log"
    assert log_path.exists()


def test_run_start_writes_event(logger, tmp_path):
    logger.run_start("scheduled", "llama3.2", 5)
    log_path = tmp_path / "logs" / f"phantom-{date.today()}.log"
    events = _read_jsonl(str(log_path))
    assert any(e.get("event") == "run_start" and e.get("queue_size") == 5 for e in events)


def test_topic_start_and_done(logger, tmp_path):
    note = Note(slug="ai-research", name="AI Research", type="tech", priority="high")
    logger.topic_start(note, position=1, total=3)
    logger.topic_done(note, elapsed_s=12.5, sources=2, memories=1, iterations=4)

    log_path = tmp_path / "logs" / f"phantom-{date.today()}.log"
    events = _read_jsonl(str(log_path))
    assert any(e.get("event") == "topic_start" and e.get("slug") == "ai-research" for e in events)
    done = next(e for e in events if e.get("event") == "topic_done")
    assert done["sources"] == 2
    assert done["iterations"] == 4


def test_topic_failed_writes_error(logger, tmp_path):
    note = Note(slug="broken", name="Broken Topic")
    logger.topic_failed(note, "Timeout", "traceback here")
    log_path = tmp_path / "logs" / f"phantom-{date.today()}.log"
    events = _read_jsonl(str(log_path))
    failed = next(e for e in events if e.get("event") == "topic_failed")
    assert failed["level"] == "ERROR"
    assert "Timeout" in failed["error"]


def test_warn_event(logger, tmp_path):
    logger.warn("source_fetch_failed", url="https://example.com", topic="test")
    log_path = tmp_path / "logs" / f"phantom-{date.today()}.log"
    events = _read_jsonl(str(log_path))
    warn = next(e for e in events if e.get("event") == "source_fetch_failed")
    assert warn["level"] == "WARN"
    assert warn["url"] == "https://example.com"


def test_run_done(logger, tmp_path):
    logger.run_done(completed=8, failed=2, total_elapsed_s=120.5)
    log_path = tmp_path / "logs" / f"phantom-{date.today()}.log"
    events = _read_jsonl(str(log_path))
    done = next(e for e in events if e.get("event") == "run_done")
    assert done["topics_completed"] == 8
    assert done["topics_failed"] == 2


def test_disabled_logger_does_not_crash(tmp_path, monkeypatch):
    monkeypatch.setattr("config.cfg._data", {
        "logging": {"enabled": False, "log_dir": str(tmp_path / "logs"), "level": "INFO", "max_log_age_days": 30},
        "schedule": {"max_parallel_workers": 1},
    })
    from logger import PhantomLogger
    log = PhantomLogger()
    note = Note(slug="x", name="X")
    log.run_start("scheduled", "llama3.2", 1)
    log.topic_failed(note, "error")
    log.close()
    # No log file created when disabled
    assert not (tmp_path / "logs").exists() or not any((tmp_path / "logs").iterdir())


def test_logger_never_crashes_on_bad_path(monkeypatch):
    """Logger with unwritable path → _enabled=False, no exception."""
    monkeypatch.setattr("config.cfg._data", {
        "logging": {"enabled": True, "log_dir": "/nonexistent/path/that/cannot/be/created", "level": "INFO", "max_log_age_days": 30},
        "schedule": {"max_parallel_workers": 1},
    })
    from logger import PhantomLogger
    log = PhantomLogger()
    note = Note(slug="t", name="T")
    log.run_start("test", "model", 1)
    log.topic_done(note, 1.0, 0, 0, 1)
    log.close()
    # Should not raise
