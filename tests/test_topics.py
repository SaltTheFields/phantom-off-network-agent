"""Tests for topics.py — TopicManager CRUD, queue, staleness."""
import pytest
from datetime import date, timedelta
from topics import TopicManager
from vault import VaultManager


def test_create_topic(tmp_vault):
    topics = TopicManager(tmp_vault)
    note = topics.create_topic("AI Research", type="tech", priority="high", tags=["ai"])
    assert tmp_vault.note_exists(note.slug)
    assert note.status == "queued"
    assert note.type == "tech"
    assert note.priority == "high"
    assert "ai" in note.tags


def test_create_topic_duplicate_raises(tmp_vault):
    topics = TopicManager(tmp_vault)
    topics.create_topic("AI Research")
    with pytest.raises(ValueError, match="already exists"):
        topics.create_topic("AI Research")


def test_get_topic_by_name(tmp_vault):
    topics = TopicManager(tmp_vault)
    topics.create_topic("Large Language Models", type="tech")
    note = topics.get_topic("Large Language Models")
    assert note is not None
    assert note.slug == "large-language-models"


def test_get_topic_partial_match(tmp_vault):
    topics = TopicManager(tmp_vault)
    topics.create_topic("Quantum Computing")
    note = topics.get_topic("quantum")
    assert note is not None


def test_update_status(tmp_vault):
    topics = TopicManager(tmp_vault)
    note = topics.create_topic("AI Research")
    topics.update_status(note.slug, "active")
    updated = tmp_vault.read_note(note.slug)
    assert updated.status == "active"


def test_archive_topic(tmp_vault):
    topics = TopicManager(tmp_vault)
    note = topics.create_topic("Old Topic")
    topics.archive_topic(note.slug)
    updated = tmp_vault.read_note(note.slug)
    assert updated.status == "archived"


def test_mark_researched(tmp_vault):
    topics = TopicManager(tmp_vault)
    note = topics.create_topic("AI Research")
    topics.mark_researched(note.slug)
    updated = tmp_vault.read_note(note.slug)
    assert updated.last_researched == str(date.today())
    assert updated.status == "active"


def test_get_research_candidates_queued(tmp_vault):
    topics = TopicManager(tmp_vault)
    topics.create_topic("Topic A", priority="high")
    topics.create_topic("Topic B", priority="low")
    candidates = topics.get_research_candidates()
    assert len(candidates) == 2
    # High priority first
    assert candidates[0].priority == "high"


def test_stale_topic_included(tmp_vault):
    topics = TopicManager(tmp_vault)
    note = topics.create_topic("Stale Topic")
    # Simulate researched 30 days ago
    stale_date = str(date.today() - timedelta(days=30))
    topics.mark_researched(note.slug, research_date=stale_date)
    stale = topics.get_stale_topics()
    assert any(n.slug == note.slug for n in stale)


def test_fresh_topic_not_stale(tmp_vault):
    topics = TopicManager(tmp_vault)
    note = topics.create_topic("Fresh Topic", refresh_interval_days=30)
    topics.mark_researched(note.slug)  # researched today
    stale = topics.get_stale_topics()
    assert not any(n.slug == note.slug for n in stale)


def test_index_created_after_create(tmp_vault):
    import os
    topics = TopicManager(tmp_vault)
    topics.create_topic("Indexed Topic")
    index_path = os.path.join(tmp_vault.vault_dir, "_index.md")
    assert os.path.exists(index_path)
    with open(index_path, encoding="utf-8") as f:
        assert "Indexed Topic" in f.read()
