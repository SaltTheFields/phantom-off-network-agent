import re
import json
import os
import random
from datetime import date, datetime
from vault import VaultManager, Note
from config import cfg

PRIORITY_ORDER = {"high": 0, "medium": 1, "low": 2}
VALID_STATUSES = (
    "queued",             # pending research
    "active",             # researched at least once
    "archived",           # user-archived, skip
    # ── Tree statuses ──────────────────────────────────────────────────────
    "planning",           # LLM decomposing into children (transient)
    "waiting_on_children",# parent waiting for all children to finish
    "synthesizing",       # claimed by exactly one worker for roll-up
    "complete",           # synthesis done — final state for tree roots
)
VALID_TYPES = ("research", "person", "tech", "event", "concept")
VALID_PRIORITIES = ("high", "medium", "low")


class TopicManager:
    def __init__(self, vault: VaultManager):
        self.vault = vault

    # ── CRUD ──────────────────────────────────────────────────────────────────

    def create_topic(
        self,
        name: str,
        type: str = "research",
        status: str = "queued",
        priority: str = "medium",
        tags: list[str] = None,
        refresh_interval_days: int = None,
    ) -> Note:
        slug = self.vault.name_to_slug(name)
        if self.vault.note_exists(slug):
            raise ValueError(f"Topic already exists: {name} (slug: {slug})")

        interval = refresh_interval_days or cfg.get("vault.default_refresh_interval_days", 7)
        note = Note(
            slug=slug,
            name=name,
            type=type if type in VALID_TYPES else "research",
            status=status if status in VALID_STATUSES else "queued",
            priority=priority if priority in VALID_PRIORITIES else "medium",
            tags=tags or [],
            created=str(date.today()),
            last_researched="",
            refresh_interval_days=int(interval),
            body=f"# {name}\n\n*Not yet researched.*\n",
        )
        self.vault.write_note(note)
        self.vault.rebuild_index()
        self.vault.rebuild_backlinks()
        return note

    def get_topic(self, name_or_slug: str) -> Note | None:
        # Try as slug first
        slug = self.vault.name_to_slug(name_or_slug)
        note = self.vault.read_note(slug)
        if note:
            return note
        # Try exact slug match (already a slug)
        note = self.vault.read_note(name_or_slug)
        if note:
            return note
        # Fuzzy: case-insensitive name match across all notes
        search = name_or_slug.lower()
        for s in self.vault.all_slugs():
            n = self.vault.read_note(s)
            if n and n.name.lower() == search:
                return n
        # Partial match fallback
        for s in self.vault.all_slugs():
            n = self.vault.read_note(s)
            if n and search in n.name.lower():
                return n
        return None

    def list_topics(self, status: str = None, type: str = None) -> list[Note]:
        notes = []
        for slug in self.vault.all_slugs():
            note = self.vault.read_note(slug)
            if not note:
                continue
            if status and note.status != status:
                continue
            if type and note.type != type:
                continue
            notes.append(note)
        return notes

    def update_status(self, slug: str, status: str) -> bool:
        note = self.vault.read_note(slug)
        if not note:
            return False
        note.status = status
        self.vault.write_note(note)
        self.vault.rebuild_index()
        self.vault.rebuild_backlinks()
        return True

    def archive_topic(self, slug: str) -> bool:
        return self.update_status(slug, "archived")

    def mark_researched(self, slug: str, research_date: str = None) -> bool:
        note = self.vault.read_note(slug)
        if not note:
            return False
        note.last_researched = research_date or str(date.today())
        note.status = "active"
        self.vault.write_note(note)
        return True

    # ── Queue management ──────────────────────────────────────────────────────

    def get_next_queued(self) -> Note | None:
        queued = self.list_topics(status="queued")
        if not queued:
            return None
        # Sort: priority first, then oldest created
        queued.sort(key=lambda n: (PRIORITY_ORDER.get(n.priority, 1), n.created))
        return queued[0]

    def get_stale_topics(self) -> list[Note]:
        if not cfg.get("schedule.stale_check_enabled", True):
            return []
        today = date.today()
        stale = []
        for note in self.list_topics(status="active"):
            if not note.last_researched:
                stale.append(note)
                continue
            try:
                last = datetime.strptime(note.last_researched, "%Y-%m-%d").date()
                days_since = (today - last).days
                if days_since >= note.refresh_interval_days:
                    stale.append(note)
            except ValueError:
                stale.append(note)  # bad date → treat as stale
        stale.sort(key=lambda n: (PRIORITY_ORDER.get(n.priority, 1), n.last_researched or ""))
        return stale

    def get_research_candidates(self) -> list[Note]:
        """
        Leaf-first candidates: queued + stale active notes, excluding nodes that
        are waiting, synthesizing, planning, or complete (tree-internal states).
        Pure leaf nodes (child_count == 0) are promoted to the front.
        """
        _SKIP_STATUSES = {"waiting_on_children", "synthesizing", "planning", "complete", "archived"}
        queued = self.list_topics(status="queued")
        stale = self.get_stale_topics()
        seen: set[str] = set()
        combined = []
        for note in queued + stale:
            if note.slug not in seen and note.status not in _SKIP_STATUSES:
                combined.append(note)
                seen.add(note.slug)
        # Leaf nodes first (child_count == 0), then sort by priority
        combined.sort(key=lambda n: (
            1 if n.child_count > 0 else 0,       # 0 = leaf, 1 = non-leaf
            PRIORITY_ORDER.get(n.priority, 1),
            n.created,
        ))
        return combined

    # ── Tree management ───────────────────────────────────────────────────────

    def create_child_topic(
        self,
        parent_slug: str,
        child_name: str,
        type: str = "research",
        priority: str = "medium",
        tags: list[str] = None,
    ) -> Note:
        """
        Create a child topic linked to a parent.
        If the slug already exists (cross-pollination), return the existing note
        and add the parent_slug link if it's currently a root (tree_depth==0).
        Does NOT update the parent's children_slugs — caller (planner) handles that.
        """
        child_slug = self.vault.name_to_slug(child_name)

        # Cross-pollination: same sub-topic referenced by two parents
        if self.vault.note_exists(child_slug):
            existing = self.vault.read_note(child_slug)
            if existing:
                return existing

        parent = self.vault.read_note(parent_slug)
        parent_depth = parent.tree_depth if parent else 0
        interval = cfg.get("vault.default_refresh_interval_days", 7)

        note = Note(
            slug=child_slug,
            name=child_name,
            type=type if type in VALID_TYPES else "research",
            status="queued",
            priority=priority if priority in VALID_PRIORITIES else "medium",
            tags=tags or (parent.tags if parent else []),
            created=str(date.today()),
            refresh_interval_days=int(interval),
            body=f"# {child_name}\n\n*Not yet researched.*\n",
            parent_slug=parent_slug,
            tree_depth=parent_depth + 1,
        )
        self.vault.write_note(note)
        return note

    def on_child_completed(self, parent_slug: str) -> str:
        """
        Called after a child finishes research.
        Atomically increments children_done on the parent.
        If all children are done, tries to claim synthesis:
          - Transitions parent to 'synthesizing' if the claim succeeds.
          - Returns 'synthesizing' if this caller won, 'waiting' otherwise.
        Returns 'not_ready' if children still pending, 'no_parent' if parent missing.
        """
        if not parent_slug:
            return "no_parent"
        done, total = self.vault.atomic_increment_children_done(parent_slug)
        if total == 0 or done < total:
            return "not_ready"
        # All children done — race to claim synthesis
        claimed = self.vault.atomic_claim_synthesis(parent_slug)
        return "synthesizing" if claimed else "waiting"

    def get_synthesis_candidates(self) -> list[Note]:
        """Return notes with status='synthesizing' — ready for roll-up worker."""
        return self.list_topics(status="synthesizing")

    def mark_complete(self, slug: str, last_researched: str = None) -> bool:
        """Mark a tree root as complete after synthesis."""
        note = self.vault.read_note(slug)
        if not note:
            return False
        note.status = "complete"
        note.last_researched = last_researched or str(date.today())
        self.vault.write_note(note)
        return True

    # ── Display ───────────────────────────────────────────────────────────────

    def format_topic_list(self, topics: list[Note]) -> str:
        if not topics:
            return "No topics found."
        lines = []
        by_status: dict[str, list[Note]] = {}
        for n in topics:
            by_status.setdefault(n.status, []).append(n)

        for status in ("queued", "active", "archived"):
            group = by_status.get(status, [])
            if not group:
                continue
            lines.append(f"\n{status.upper()} ({len(group)})")
            lines.append("─" * 40)
            for n in sorted(group, key=lambda x: x.name):
                tags = f"  [{', '.join(n.tags)}]" if n.tags else ""
                researched = f"  last: {n.last_researched}" if n.last_researched else "  never researched"
                lines.append(f"  {n.priority:6}  {n.type:8}  {n.name}{tags}{researched}")
        return "\n".join(lines)

    def format_topic_card(self, note: Note) -> str:
        lines = [
            f"\n{'═' * 50}",
            f"  {note.name}",
            f"{'═' * 50}",
            f"  Type     : {note.type}",
            f"  Status   : {note.status}",
            f"  Priority : {note.priority}",
            f"  Tags     : {', '.join(note.tags) or 'none'}",
            f"  Created  : {note.created}",
            f"  Researched: {note.last_researched or 'never'}",
            f"  Refresh  : every {note.refresh_interval_days} days",
            "",
        ]
        if note.forward_links:
            lines.append(f"  Links to : {', '.join(note.forward_links)}")
        backlinks = self.vault._get_backlinks_for(note.slug)
        if backlinks:
            lines.append(f"  Linked by: {', '.join(backlinks)}")

        # Preview first 300 chars of body (skip heading)
        preview = note.body.strip()
        preview = re.sub(r"^#[^\n]*\n", "", preview).strip()
        if preview:
            lines.append("")
            lines.append("  Preview:")
            lines.append("  " + preview[:300].replace("\n", "\n  ") + ("..." if len(preview) > 300 else ""))
        lines.append(f"{'═' * 50}")
        return "\n".join(lines)

    def format_topic_graph(self) -> str:
        all_notes = self.list_topics()
        if not all_notes:
            return "No topics in vault yet."

        # Build full backlink map
        backlink_map: dict[str, list[str]] = {}
        for note in all_notes:
            for link_name in note.forward_links:
                target_slug = self.vault.name_to_slug(link_name)
                backlink_map.setdefault(target_slug, [])
                if note.name not in backlink_map[target_slug]:
                    backlink_map[target_slug].append(note.name)

        active_notes = [n for n in all_notes if n.status != "archived"]
        archived_count = len(all_notes) - len(active_notes)

        lines = [
            f"\nTopic Graph ({len(active_notes)} notes)",
            "═" * 50,
            "",
        ]

        for note in sorted(active_notes, key=lambda n: n.name):
            lines.append(f"{note.name} ({note.type}/{note.status})")
            if note.forward_links:
                fwd = ", ".join(f"[[{l}]]" for l in note.forward_links)
                lines.append(f"  → {fwd}")
            back = backlink_map.get(note.slug, [])
            if back:
                bk = ", ".join(f"[[{b}]]" for b in back)
                lines.append(f"  ← {bk}")
            if not note.forward_links and not backlink_map.get(note.slug):
                lines.append("  (no links)")
            lines.append("")

        if archived_count:
            lines.append(f"[{archived_count} archived topic(s) hidden]")

        return "\n".join(lines)

    # ── Loop / depth-based selection ─────────────────────────────────────────

    def get_loop_candidates(self) -> list[Note]:
        """
        Return all non-archived topics sorted for loop research.
        Combines queued + active (stale or not) — every topic is always eligible
        in loop mode. Sort key: (depth ASC, priority weight ASC).
        """
        _SKIP = {"archived", "waiting_on_children", "synthesizing", "planning", "complete"}
        all_notes = [n for n in self.list_topics() if n.status not in _SKIP]
        all_notes.sort(key=lambda n: (
            n.research_depth,
            PRIORITY_ORDER.get(n.priority, 1),
            n.last_researched or "0000-00-00",
        ))
        return all_notes

    def weighted_pick(self, candidates: list[Note]) -> Note | None:
        """
        Pick one topic using weighted random selection.
        - Depth-0 / never-run topics are always guaranteed to run first (priority-sorted among themselves)
        - Once all depth-0 topics are done, exponential decay + soft cap governs the rest
        - Every topic always has a non-zero chance (no starvation)
        """
        if not candidates:
            return None
        if len(candidates) == 1:
            return candidates[0]

        # Fast path: if any depth-0 or never-researched topics exist, pick the
        # highest-priority one immediately — don't randomise, just clear the backlog.
        fresh = [n for n in candidates if n.research_depth == 0 or not n.last_researched]
        if fresh:
            fresh.sort(key=lambda n: (PRIORITY_ORDER.get(n.priority, 1), n.created or ""))
            return fresh[0]

        PRIORITY_WEIGHT = {"high": 10, "medium": 3, "low": 1}
        soft_cap = cfg.get("schedule.depth_soft_cap", 5)

        def _weight(note: Note) -> float:
            base = PRIORITY_WEIGHT.get(note.priority, 3)
            # Exponential decay: 0.7^depth
            # depth 1→0.70, 2→0.49, 3→0.34, 4→0.24, 5→0.17, 6→0.12
            decay = 0.7 ** note.research_depth
            # Hard soft-cap penalty: topics at depth >= cap are heavily deprioritised
            if note.research_depth >= soft_cap:
                decay *= 0.1
            return max(0.01, base * decay)

        weights = [_weight(n) for n in candidates]
        return random.choices(candidates, weights=weights, k=1)[0]

    def increment_depth(self, slug: str) -> int:
        """Increment research_depth for a topic. Returns new depth."""
        note = self.vault.read_note(slug)
        if not note:
            return 0
        note.research_depth += 1
        self.vault.write_note(note)
        return note.research_depth

    # ── Bulk import ───────────────────────────────────────────────────────────

    def parse_import_file(self, filepath: str) -> tuple[list[dict], list[str]]:
        """
        Parse a .txt or .json import file.
        Returns (parsed_rows, errors).
        Each row is a dict matching create_topic() kwargs.
        """
        if not os.path.exists(filepath):
            return [], [f"File not found: {filepath}"]

        ext = os.path.splitext(filepath)[1].lower()
        rows = []
        errors = []

        if ext == ".json":
            try:
                with open(filepath, "r", encoding="utf-8") as f:
                    data = json.load(f)
                if not isinstance(data, list):
                    return [], ["JSON file must contain a top-level array of topic objects"]
                for i, item in enumerate(data):
                    row, err = self._validate_row(item, line_num=i + 1)
                    if err:
                        errors.append(err)
                    else:
                        rows.append(row)
            except json.JSONDecodeError as e:
                return [], [f"Invalid JSON: {e}"]

        else:
            # Plain text: name | type | priority | tags | refresh_days
            with open(filepath, "r", encoding="utf-8") as f:
                for line_num, raw_line in enumerate(f, 1):
                    line = raw_line.strip()
                    if not line or line.startswith("#"):
                        continue
                    parts = [p.strip() for p in line.split("|")]
                    item = {"name": parts[0] if parts else ""}
                    if len(parts) > 1 and parts[1]:
                        item["type"] = parts[1]
                    if len(parts) > 2 and parts[2]:
                        item["priority"] = parts[2]
                    if len(parts) > 3 and parts[3]:
                        item["tags"] = [t.strip() for t in parts[3].split(",") if t.strip()]
                    if len(parts) > 4 and parts[4].strip().isdigit():
                        item["refresh_interval_days"] = int(parts[4].strip())
                    row, err = self._validate_row(item, line_num=line_num)
                    if err:
                        errors.append(err)
                    else:
                        rows.append(row)

        return rows, errors

    def _validate_row(self, item: dict, line_num: int = 0) -> tuple[dict | None, str | None]:
        name = item.get("name", "").strip()
        if not name:
            return None, f"Line {line_num}: missing topic name"

        topic_type = item.get("type", "research")
        if topic_type not in VALID_TYPES:
            return None, f"Line {line_num}: invalid type '{topic_type}' for '{name}' (valid: {', '.join(VALID_TYPES)})"

        priority = item.get("priority", "medium")
        if priority not in VALID_PRIORITIES:
            return None, f"Line {line_num}: invalid priority '{priority}' for '{name}' (valid: {', '.join(VALID_PRIORITIES)})"

        tags = item.get("tags", [])
        if isinstance(tags, str):
            tags = [t.strip() for t in tags.split(",") if t.strip()]

        interval = item.get("refresh_interval_days", cfg.get("vault.default_refresh_interval_days", 7))
        try:
            interval = int(interval)
        except (ValueError, TypeError):
            interval = 7

        return {
            "name": name,
            "type": topic_type,
            "priority": priority,
            "tags": tags,
            "refresh_interval_days": interval,
        }, None

    def import_topics(self, filepath: str) -> str:
        """
        Parse, preview, confirm, and create topics from a file.
        Returns a status string for the CLI.
        """
        rows, errors = self.parse_import_file(filepath)

        if not rows and errors:
            return "Import failed:\n" + "\n".join(f"  {e}" for e in errors)

        # Classify each row
        new_rows = []
        skip_rows = []
        for row in rows:
            slug = self.vault.name_to_slug(row["name"])
            if self.vault.note_exists(slug):
                skip_rows.append(row)
            else:
                new_rows.append(row)

        # Preview table
        col = 38
        lines = [f"\nImport preview ({len(rows)} topic(s) from {os.path.basename(filepath)}):"]
        for row in rows:
            slug = self.vault.name_to_slug(row["name"])
            exists = self.vault.note_exists(slug)
            tag = "[SKIP]" if exists else "[NEW] "
            name_col = row["name"][:col].ljust(col)
            lines.append(
                f"  {tag}  {name_col}  {row['type']:<9}  {row['priority']:<7}  {row['refresh_interval_days']}d"
            )
        if errors:
            lines.append("\nWarnings (rows skipped):")
            for e in errors:
                lines.append(f"  [WARN]  {e}")

        print("\n".join(lines))

        if not new_rows:
            return "Nothing to create — all topics already exist."

        ans = input(f"\nCreate {len(new_rows)} new topic(s)? [y/N]: ").strip().lower()
        if ans != "y":
            return "Cancelled."

        created = 0
        skipped = 0
        failed = 0

        print("\nCreating...")
        for row in rows:
            slug = self.vault.name_to_slug(row["name"])
            if self.vault.note_exists(slug):
                print(f"  Skipped : {row['name']} (already exists)")
                skipped += 1
                continue
            try:
                self.create_topic(**row)
                print(f"  Created : {row['name']}")
                created += 1
            except Exception as e:
                print(f"  ERROR   : {row['name']} — {e}")
                failed += 1

        return f"\nDone. Created: {created} | Skipped: {skipped} | Errors: {failed}"

    # ── Export ────────────────────────────────────────────────────────────────

    def export_topics(self, status_filter: str = None) -> str:
        """
        Export topics to a JSON file. Returns a status string.
        Output file is valid input for import_topics().
        """
        notes = self.list_topics(status=status_filter if status_filter != "all" else None)
        if not notes:
            label = f"{status_filter} " if status_filter and status_filter != "all" else ""
            return f"No {label}topics to export."

        today = str(date.today())
        suffix = f"-{status_filter}" if status_filter and status_filter != "all" else ""
        filename = f"topic-export{suffix}-{today}.json"

        data = []
        for n in sorted(notes, key=lambda x: x.name):
            data.append({
                "name": n.name,
                "type": n.type,
                "priority": n.priority,
                "tags": n.tags,
                "refresh_interval_days": n.refresh_interval_days,
            })

        with open(filename, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)

        label = f"{status_filter} " if status_filter and status_filter != "all" else ""
        return f"Exported {len(data)} {label}topic(s) to: {filename}"


