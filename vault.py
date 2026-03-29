import os
import re
import threading
from dataclasses import dataclass, field
from datetime import date


@dataclass
class Note:
    slug: str
    name: str
    type: str = "research"
    status: str = "queued"
    priority: str = "medium"
    tags: list = field(default_factory=list)
    created: str = ""
    last_researched: str = ""
    refresh_interval_days: int = 7
    body: str = ""
    forward_links: list = field(default_factory=list)
    # Research stats (cumulative across runs)
    research_runs: int = 0
    total_sources_fetched: int = 0
    total_memories_saved: int = 0
    last_run_elapsed_s: float = 0
    last_run_iterations: int = 0


# ── Frontmatter parser (no PyYAML) ────────────────────────────────────────────

def _parse_frontmatter(text: str) -> tuple[dict, str]:
    """Split a markdown file into (frontmatter_dict, body_str).
    Returns ({}, full_text) if no frontmatter found."""
    if not text.startswith("---"):
        return {}, text
    end = text.find("\n---", 3)
    if end == -1:
        return {}, text
    fm_block = text[3:end].strip()
    body = text[end + 4:].lstrip("\n")
    return _parse_yaml_subset(fm_block), body


def _parse_yaml_subset(block: str) -> dict:
    """Parse simple YAML: strings, ints, and [list, of, strings]."""
    result = {}
    for line in block.splitlines():
        line = line.strip()
        if not line or ":" not in line:
            continue
        key, _, raw = line.partition(":")
        key = key.strip()
        raw = raw.strip()
        if raw.startswith("[") and raw.endswith("]"):
            items = [i.strip().strip('"').strip("'") for i in raw[1:-1].split(",") if i.strip()]
            result[key] = items
        elif raw.isdigit():
            result[key] = int(raw)
        else:
            result[key] = raw.strip('"').strip("'")
    return result


def _render_frontmatter(meta: dict) -> str:
    lines = ["---"]
    for key, value in meta.items():
        if isinstance(value, list):
            items = ", ".join(value)
            lines.append(f"{key}: [{items}]")
        else:
            lines.append(f"{key}: {value}")
    lines.append("---")
    return "\n".join(lines)


# ── VaultManager ──────────────────────────────────────────────────────────────

class VaultManager:
    BACKLINK_START = "<!-- backlinks-start -->"
    BACKLINK_END = "<!-- backlinks-end -->"

    def __init__(self, vault_dir: str = "vault"):
        self.vault_dir = vault_dir
        self._lock = threading.RLock()  # RLock: rebuild_backlinks calls read_note internally
        os.makedirs(vault_dir, exist_ok=True)
        os.makedirs(os.path.join(vault_dir, "daily"), exist_ok=True)

    def _path(self, slug: str) -> str:
        return os.path.join(self.vault_dir, f"{slug}.md")

    def note_exists(self, slug: str) -> bool:
        with self._lock:
            return os.path.exists(self._path(slug))

    def all_slugs(self) -> list[str]:
        with self._lock:
            slugs = []
            for fname in os.listdir(self.vault_dir):
                if fname.endswith(".md") and not fname.startswith("_"):
                    slugs.append(fname[:-3])
            return sorted(slugs)

    def name_to_slug(self, name: str) -> str:
        slug = name.lower()
        slug = re.sub(r"[^\w\s-]", "", slug)
        slug = re.sub(r"[\s_]+", "-", slug)
        slug = re.sub(r"-+", "-", slug)
        return slug.strip("-")

    # ── Read / Write ──────────────────────────────────────────────────────────

    def read_note(self, slug: str) -> Note | None:
        with self._lock:
            path = self._path(slug)
            if not os.path.exists(path):
                return None
            with open(path, "r", encoding="utf-8") as f:
                text = f.read()
        meta, body = _parse_frontmatter(text)
        note = Note(
            slug=slug,
            name=meta.get("name", slug),
            type=meta.get("type", "research"),
            status=meta.get("status", "active"),
            priority=meta.get("priority", "medium"),
            tags=meta.get("tags", []),
            created=meta.get("created", ""),
            last_researched=meta.get("last_researched", ""),
            refresh_interval_days=int(meta.get("refresh_interval_days", 7)),
            body=body,
            forward_links=self.extract_wikilinks(body),
            research_runs=int(meta.get("research_runs", 0)),
            total_sources_fetched=int(meta.get("total_sources_fetched", 0)),
            total_memories_saved=int(meta.get("total_memories_saved", 0)),
            last_run_elapsed_s=float(meta.get("last_run_elapsed_s", 0)),
            last_run_iterations=int(meta.get("last_run_iterations", 0)),
        )
        return note

    def write_note(self, note: Note) -> None:
        """Write note to disk. Does NOT rebuild backlinks — caller must do that explicitly."""
        meta = {
            "name": note.name,
            "slug": note.slug,
            "type": note.type,
            "status": note.status,
            "priority": note.priority,
            "tags": note.tags,
            "created": note.created or str(date.today()),
            "last_researched": note.last_researched or "",
            "refresh_interval_days": note.refresh_interval_days,
            "research_runs": note.research_runs,
            "total_sources_fetched": note.total_sources_fetched,
            "total_memories_saved": note.total_memories_saved,
            "last_run_elapsed_s": note.last_run_elapsed_s,
            "last_run_iterations": note.last_run_iterations,
        }
        body = note.body
        footer = f"\n---\n*Last researched: {note.last_researched or 'never'} | Refresh interval: {note.refresh_interval_days} days*\n"
        body = re.sub(r"\n---\n\*Last researched:.*$", "", body, flags=re.DOTALL).rstrip()
        body = body + "\n" + footer
        content = _render_frontmatter(meta) + "\n\n" + body
        with self._lock:
            with open(self._path(note.slug), "w", encoding="utf-8") as f:
                f.write(content)

    def delete_note(self, slug: str) -> bool:
        """Delete note. Does NOT rebuild backlinks — caller must do that explicitly."""
        with self._lock:
            path = self._path(slug)
            if os.path.exists(path):
                os.remove(path)
                return True
        return False

    # ── WikiLinks ─────────────────────────────────────────────────────────────

    def extract_wikilinks(self, body: str) -> list[str]:
        return re.findall(r"\[\[([^\]]+)\]\]", body)

    # ── Backlinks ─────────────────────────────────────────────────────────────

    def rebuild_backlinks(self) -> None:
        """Scan every note, build reverse link map, rewrite backlink sections."""
        with self._lock:
            backlink_map: dict[str, list[str]] = {}

            for slug in os.listdir(self.vault_dir):
                if not slug.endswith(".md") or slug.startswith("_"):
                    continue
                slug_key = slug[:-3]
                note = self.read_note(slug_key)
                if not note:
                    continue
                for link_name in note.forward_links:
                    target_slug = self.name_to_slug(link_name)
                    backlink_map.setdefault(target_slug, [])
                    if note.name not in backlink_map[target_slug]:
                        backlink_map[target_slug].append(note.name)

            for slug in os.listdir(self.vault_dir):
                if not slug.endswith(".md") or slug.startswith("_"):
                    continue
                slug_key = slug[:-3]
                path = self._path(slug_key)
                with open(path, "r", encoding="utf-8") as f:
                    content = f.read()

                backlinks = backlink_map.get(slug_key, [])
                new_section = self._render_backlinks_section(backlinks)

                if self.BACKLINK_START in content:
                    content = re.sub(
                        re.escape(self.BACKLINK_START) + r".*?" + re.escape(self.BACKLINK_END),
                        new_section,
                        content,
                        flags=re.DOTALL,
                    )
                else:
                    footer_match = re.search(r"\n---\n\*Last researched:", content)
                    if footer_match:
                        insert_at = footer_match.start()
                        content = content[:insert_at] + "\n\n" + new_section + content[insert_at:]
                    else:
                        content = content.rstrip() + "\n\n" + new_section + "\n"

                with open(path, "w", encoding="utf-8") as f:
                    f.write(content)

    def _render_backlinks_section(self, source_names: list[str]) -> str:
        lines = [self.BACKLINK_START, "## Backlinks", ""]
        if source_names:
            for name in source_names:
                lines.append(f"- [[{name}]] — links here")
        else:
            lines.append("*No backlinks yet.*")
        lines.append(self.BACKLINK_END)
        return "\n".join(lines)

    def _get_backlinks_for(self, slug: str) -> list[str]:
        result = []
        for s in self.all_slugs():
            note = self.read_note(s)
            if note and slug in [self.name_to_slug(l) for l in note.forward_links]:
                result.append(note.name)
        return result

    # ── Index ─────────────────────────────────────────────────────────────────

    def rebuild_index(self) -> None:
        with self._lock:
            slugs = [f[:-3] for f in os.listdir(self.vault_dir)
                     if f.endswith(".md") and not f.startswith("_")]
            notes = []
            for s in slugs:
                n = self.read_note(s)
                if n:
                    notes.append(n)

            queued = [n for n in notes if n.status == "queued"]
            active = [n for n in notes if n.status == "active"]
            archived = [n for n in notes if n.status == "archived"]

            lines = [
                "---",
                "type: index",
                f"updated: {date.today()}",
                f"total_notes: {len(notes)}",
                "---",
                "",
                "# Phantom Research Vault",
                "",
                f"> {len(notes)} topics tracked — {len(active)} active, {len(queued)} queued, {len(archived)} archived",
                "",
            ]

            def _section(title: str, group: list) -> list:
                if not group:
                    return []
                out = [f"## {title}", ""]
                for n in sorted(group, key=lambda x: x.name):
                    tags = f" `{'` `'.join(n.tags)}`" if n.tags else ""
                    researched = f" — *{n.last_researched}*" if n.last_researched else ""
                    out.append(f"- [[{n.name}]] ({n.type}, {n.priority}){tags}{researched}")
                out.append("")
                return out

            lines += _section("Active", active)
            lines += _section("Queued", queued)
            lines += _section("Archived", archived)

            index_path = os.path.join(self.vault_dir, "_index.md")
            with open(index_path, "w", encoding="utf-8") as f:
                f.write("\n".join(lines))

    # ── Conflict detection ────────────────────────────────────────────────────

    def find_contradictions(self, slug: str, new_content: str) -> list[str]:
        note = self.read_note(slug)
        if not note or not note.body:
            return []

        # Extract existing bullet facts
        existing_facts = re.findall(r"^[-*]\s+(.+)$", note.body, re.MULTILINE)
        conflicts = []

        negation_words = ["not", "no longer", "never", "false", "incorrect", "wrong",
                          "was previously", "used to", "deprecated", "removed", "discontinued"]
        for fact in existing_facts:
            fact_lower = fact.lower()
            for sentence in re.split(r"[.!?]", new_content):
                sent_lower = sentence.lower()
                # Look for sentences that reference the same subject but negate
                first_word = fact_lower.split()[0] if fact_lower.split() else ""
                if first_word and first_word in sent_lower:
                    for neg in negation_words:
                        if neg in sent_lower and neg not in fact_lower:
                            conflicts.append(
                                f"> [!warning] Potential Conflict\n"
                                f"> Existing note states: \"{fact.strip()}\"\n"
                                f"> New content suggests: \"{sentence.strip()}\""
                            )
                            break

        return conflicts
