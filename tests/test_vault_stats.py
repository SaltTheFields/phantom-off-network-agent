"""Tests for vault.py — frontmatter stats fields (Task 4)."""
import pytest
from vault import VaultManager, Note


def test_stats_default_to_zero(tmp_vault):
    note = Note(slug="test", name="Test Topic")
    tmp_vault.write_note(note)
    loaded = tmp_vault.read_note("test")
    assert loaded.research_runs == 0
    assert loaded.total_sources_fetched == 0
    assert loaded.total_memories_saved == 0
    assert loaded.last_run_elapsed_s == 0
    assert loaded.last_run_iterations == 0


def test_stats_persist_roundtrip(tmp_vault):
    note = Note(slug="tracked", name="Tracked Topic")
    note.research_runs = 3
    note.total_sources_fetched = 12
    note.total_memories_saved = 5
    note.last_run_elapsed_s = 42.7
    note.last_run_iterations = 6
    tmp_vault.write_note(note)

    loaded = tmp_vault.read_note("tracked")
    assert loaded.research_runs == 3
    assert loaded.total_sources_fetched == 12
    assert loaded.total_memories_saved == 5
    assert loaded.last_run_elapsed_s == 42.7
    assert loaded.last_run_iterations == 6


def test_stats_increment_across_runs(tmp_vault):
    note = Note(slug="multi-run", name="Multi Run")
    tmp_vault.write_note(note)

    # Simulate first run
    n = tmp_vault.read_note("multi-run")
    n.research_runs += 1
    n.total_sources_fetched += 3
    n.last_run_elapsed_s = 15.0
    n.last_run_iterations = 4
    tmp_vault.write_note(n)

    # Simulate second run
    n2 = tmp_vault.read_note("multi-run")
    n2.research_runs += 1
    n2.total_sources_fetched += 2
    n2.last_run_elapsed_s = 10.0
    n2.last_run_iterations = 3
    tmp_vault.write_note(n2)

    final = tmp_vault.read_note("multi-run")
    assert final.research_runs == 2
    assert final.total_sources_fetched == 5   # cumulative
    assert final.last_run_elapsed_s == 10.0   # overwritten
    assert final.last_run_iterations == 3     # overwritten


def test_existing_notes_without_stats_read_cleanly(tmp_vault):
    """Notes written without stat fields → read with default zeros."""
    # Write a note manually in the old format (no stats in frontmatter)
    path = tmp_vault._path("legacy-note")
    with open(path, "w", encoding="utf-8") as f:
        f.write("---\nname: Legacy Note\nslug: legacy-note\ntype: research\nstatus: queued\npriority: medium\ntags: []\ncreated: 2025-01-01\nlast_researched: \nrefresh_interval_days: 7\n---\n\n# Legacy Note\n\nOld content.\n")

    note = tmp_vault.read_note("legacy-note")
    assert note is not None
    assert note.research_runs == 0
    assert note.total_sources_fetched == 0
