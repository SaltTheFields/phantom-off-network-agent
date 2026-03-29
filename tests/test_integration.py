"""
Integration test — full AI Research topic lifecycle.
Uses mock_llm to simulate: read_note → web_search → update_note → done
Validates vault, backlinks, sources, digest, and index all update correctly.
"""
import os
import pytest
from vault import VaultManager
from memory import MemoryStore
from topics import TopicManager
from agents import AgentRoster
from scheduler import ResearchScheduler


def test_full_research_pipeline(tmp_path, monkeypatch, mock_llm):
    """
    Full pipeline:
      create topic → scheduler picks it up →
      agent calls read_note → web_search → update_note →
      vault note updated → backlinks rebuilt → daily digest created
    """
    # Setup isolated environment
    vault = VaultManager(str(tmp_path / "vault"))
    memory = MemoryStore(str(tmp_path / "data" / "memory.db"))
    topics = TopicManager(vault)
    roster = AgentRoster(path=str(tmp_path / "agents.json"))

    # Point config at our tmp paths so scheduler uses the right db
    from config import cfg
    monkeypatch.setattr(cfg, "get", lambda key, default=None: {
        "memory.db_path": str(tmp_path / "data" / "memory.db"),
        "vault.path": str(tmp_path / "vault"),
        "agent.max_iterations": 8,
        "schedule.generate_daily_digest": True,
        "schedule.max_parallel_workers": 1,
        "schedule.max_topics_per_run": 10,
        "schedule.stale_check_enabled": True,
        "ollama.model": "llama3.2",
        "vault.default_refresh_interval_days": 7,
        "logging.enabled": True,
        "logging.log_dir": str(tmp_path / "logs"),
        "logging.level": "INFO",
        "logging.max_log_age_days": 30,
    }.get(key, default))

    # 1. Create the primary topic
    note = topics.create_topic("AI Research", type="tech", priority="high",
                                tags=["ai", "machine-learning"])
    assert vault.note_exists(note.slug)
    assert note.status == "queued"

    # 2. Create a related topic for backlink testing
    #    (mock_llm update_note body includes [[Large Language Models]])
    topics.create_topic("Large Language Models", type="tech", tags=["llm", "ai"])

    # 3. Run scheduler with mock LLM (max_topics=1 — just AI Research)
    scheduler = ResearchScheduler(memory, vault, topics, roster=roster, max_topics=1)
    result = scheduler.run()

    # 4. Validate outcome counts
    assert result.topics_attempted == 1
    assert result.topics_succeeded == 1
    assert result.topics_failed == 0

    # 5. Validate vault note was written with content
    updated = vault.read_note(note.slug)
    assert updated is not None
    assert "AI Research" in updated.body
    assert updated.last_researched != ""
    assert updated.status == "active"

    # 6. Validate forward link was recorded
    assert "Large Language Models" in updated.forward_links

    # 7. Validate backlink appears on related topic note
    llm_note = vault.read_note(vault.name_to_slug("Large Language Models"))
    assert llm_note is not None
    assert "AI Research" in (llm_note.body or "")

    # 8. Validate source was recorded in SQLite
    sources = memory.get_sources_for_topic(note.slug)
    assert len(sources) >= 1
    assert any("example.com" in s["url"] for s in sources)

    # 9. Validate daily digest created
    assert result.digest_path != ""
    assert os.path.exists(result.digest_path)
    with open(result.digest_path, encoding="utf-8") as f:
        digest = f.read()
    assert "AI Research" in digest

    # 10. Validate index rebuilt
    index_path = os.path.join(vault.vault_dir, "_index.md")
    assert os.path.exists(index_path)
    with open(index_path, encoding="utf-8") as f:
        index = f.read()
    assert "AI Research" in index

    memory.close()


def test_failed_topic_does_not_corrupt_vault(tmp_path, monkeypatch):
    """A topic that errors during research leaves the vault intact."""
    vault = VaultManager(str(tmp_path / "vault"))
    memory = MemoryStore(str(tmp_path / "data" / "memory.db"))
    topics = TopicManager(vault)
    roster = AgentRoster(path=str(tmp_path / "agents.json"))

    from config import cfg
    monkeypatch.setattr(cfg, "get", lambda key, default=None: {
        "memory.db_path": str(tmp_path / "data" / "memory.db"),
        "vault.path": str(tmp_path / "vault"),
        "agent.max_iterations": 8,
        "schedule.generate_daily_digest": False,
        "schedule.max_parallel_workers": 1,
        "schedule.max_topics_per_run": 10,
        "schedule.stale_check_enabled": True,
        "ollama.model": "llama3.2",
        "vault.default_refresh_interval_days": 7,
        "logging.enabled": True,
        "logging.log_dir": str(tmp_path / "logs"),
        "logging.level": "INFO",
        "logging.max_log_age_days": 30,
    }.get(key, default))

    # LLM always raises
    import llm as llm_module
    from llm import OllamaConnectionError
    monkeypatch.setattr(llm_module, "chat", lambda *a, **kw: (_ for _ in ()).throw(OllamaConnectionError("down")))

    topics.create_topic("Unstable Topic", type="tech")
    scheduler = ResearchScheduler(memory, vault, topics, roster=roster, max_topics=1)
    result = scheduler.run()

    assert result.topics_failed == 1
    assert result.topics_succeeded == 0
    # Note still exists (not deleted)
    assert vault.note_exists("unstable-topic")

    memory.close()
