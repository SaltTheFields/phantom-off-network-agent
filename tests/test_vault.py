"""Tests for vault.py — read/write/backlinks/index/threading."""
import threading
import pytest
from vault import VaultManager, Note


def test_write_and_read_roundtrip(tmp_vault):
    note = Note(slug="ai-research", name="AI Research", type="tech",
                tags=["ai"], body="# AI Research\n\nSome content.")
    tmp_vault.write_note(note)
    loaded = tmp_vault.read_note("ai-research")
    assert loaded is not None
    assert loaded.name == "AI Research"
    assert loaded.type == "tech"
    assert "ai" in loaded.tags
    assert "Some content" in loaded.body


def test_note_exists(tmp_vault):
    assert tmp_vault.note_exists("nonexistent") is False
    note = Note(slug="test-note", name="Test Note")
    tmp_vault.write_note(note)
    assert tmp_vault.note_exists("test-note") is True


def test_name_to_slug_special_chars(tmp_vault):
    assert tmp_vault.name_to_slug("AI Research!") == "ai-research"
    assert tmp_vault.name_to_slug("Large Language Models") == "large-language-models"
    assert tmp_vault.name_to_slug("  spaced  ") == "spaced"


def test_extract_wikilinks(tmp_vault):
    body = "See [[Large Language Models]] and [[AI Safety]] for more."
    links = tmp_vault.extract_wikilinks(body)
    assert "Large Language Models" in links
    assert "AI Safety" in links
    assert len(links) == 2


def test_backlinks_populated_after_rebuild(tmp_vault):
    """Write two linked notes, rebuild backlinks, verify section appears."""
    note_a = Note(slug="ai-research", name="AI Research",
                  body="# AI Research\n\nSee [[Large Language Models]].")
    note_b = Note(slug="large-language-models", name="Large Language Models",
                  body="# Large Language Models\n\nFoundational models.")
    tmp_vault.write_note(note_a)
    tmp_vault.write_note(note_b)
    tmp_vault.rebuild_backlinks()

    with open(tmp_vault._path("large-language-models"), encoding="utf-8") as f:
        content = f.read()
    assert "AI Research" in content
    assert "<!-- backlinks-start -->" in content


def test_rebuild_index_creates_file(tmp_vault):
    from topics import TopicManager
    topics = TopicManager(tmp_vault)
    topics.create_topic("AI Research", type="tech")
    import os
    index_path = os.path.join(tmp_vault.vault_dir, "_index.md")
    assert os.path.exists(index_path)
    with open(index_path, encoding="utf-8") as f:
        content = f.read()
    assert "AI Research" in content


def test_all_slugs_excludes_index(tmp_vault):
    note = Note(slug="topic-one", name="Topic One")
    tmp_vault.write_note(note)
    tmp_vault.rebuild_index()
    slugs = tmp_vault.all_slugs()
    assert "topic-one" in slugs
    assert "_index" not in slugs


def test_concurrent_writes_no_corruption(tmp_vault):
    """5 threads each write a different note — all 5 readable after join."""
    names = ["Topic Alpha", "Topic Beta", "Topic Gamma", "Topic Delta", "Topic Epsilon"]

    def _write(name):
        slug = tmp_vault.name_to_slug(name)
        note = Note(slug=slug, name=name, body=f"# {name}\n\nContent.")
        tmp_vault.write_note(note)

    threads = [threading.Thread(target=_write, args=(n,)) for n in names]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    for name in names:
        slug = tmp_vault.name_to_slug(name)
        assert tmp_vault.read_note(slug) is not None, f"Missing: {name}"


def test_rebuild_backlinks_after_threaded_writes(tmp_vault):
    """After concurrent writes, single rebuild produces correct backlinks."""
    # Create hub note that links to 3 others
    hub = Note(slug="hub", name="Hub",
               body="# Hub\n\nSee [[Alpha]], [[Beta]], [[Gamma]].")
    spokes = [
        Note(slug="alpha", name="Alpha", body="# Alpha"),
        Note(slug="beta", name="Beta", body="# Beta"),
        Note(slug="gamma", name="Gamma", body="# Gamma"),
    ]

    def _write(n):
        tmp_vault.write_note(n)

    threads = [threading.Thread(target=_write, args=(n,)) for n in [hub] + spokes]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    tmp_vault.rebuild_backlinks()

    for slug in ("alpha", "beta", "gamma"):
        with open(tmp_vault._path(slug), encoding="utf-8") as f:
            content = f.read()
        assert "Hub" in content
