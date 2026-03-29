"""
Research prompt templates, one per topic type.
Each template tells the LLM what structure to produce and how to handle the vault.
"""

TOPIC_TYPES = ("research", "person", "tech", "event", "concept")

# ── Type-specific section structures ─────────────────────────────────────────

_PERSON_SECTIONS = """\
## Summary
One-paragraph overview of who this person is and why they matter.

## Background
Early life, education, career path.

## Current Role & Work
What they are doing now. Most recent projects, positions, affiliations.

## Notable Contributions
Key achievements, publications, products, ideas attributed to them.

## Controversies & Criticism
Any notable controversies, criticisms, or opposing viewpoints.

## Related Topics
[[WikiLink]] to related people, organizations, concepts. Use | to separate multiple links.

## Sources
- [Title](URL) — fetched YYYY-MM-DD"""

_TECH_SECTIONS = """\
## Summary
One-paragraph overview of what this technology is and what problem it solves.

## Current Status
Latest version, release date, maintenance status, adoption level.

## How It Works
Core concepts, architecture, key components.

## Use Cases
What it's used for, who uses it, real-world examples.

## Ecosystem
Related tools, frameworks, competitors, alternatives.

## Related Topics
[[WikiLink]] to related technologies, concepts, people. Use | to separate multiple links.

## Sources
- [Title](URL) — fetched YYYY-MM-DD"""

_EVENT_SECTIONS = """\
## Summary
One-paragraph overview of what happened and why it matters.

## Timeline
Key dates and sequence of events.

## Key Actors
Who was involved, what role they played.

## Causes
What led to this event.

## Outcomes & Aftermath
Direct results, lasting impact, ongoing consequences.

## Related Topics
[[WikiLink]] to related events, people, concepts. Use | to separate multiple links.

## Sources
- [Title](URL) — fetched YYYY-MM-DD"""

_CONCEPT_SECTIONS = """\
## Summary
One-paragraph definition and overview.

## Origins & History
Where this concept came from, how it developed.

## Core Ideas
The fundamental principles or components of this concept.

## Applications
How and where this concept is applied.

## Criticisms & Limitations
Counter-arguments, edge cases, where the concept breaks down.

## Related Topics
[[WikiLink]] to related concepts, people, fields. Use | to separate multiple links.

## Sources
- [Title](URL) — fetched YYYY-MM-DD"""

_RESEARCH_SECTIONS = """\
## Summary
One-paragraph overview of the current state of knowledge on this topic.

## Key Facts
Bullet list of the most important facts, figures, and findings.

## Details
Deeper exploration of the topic.

## Open Questions
What is still unknown, debated, or being researched.

## Related Topics
[[WikiLink]] to related topics. Use | to separate multiple links.

## Sources
- [Title](URL) — fetched YYYY-MM-DD"""

_SECTIONS_BY_TYPE = {
    "person": _PERSON_SECTIONS,
    "tech": _TECH_SECTIONS,
    "event": _EVENT_SECTIONS,
    "concept": _CONCEPT_SECTIONS,
    "research": _RESEARCH_SECTIONS,
}

# ── Update instructions per type ──────────────────────────────────────────────

_UPDATE_INSTRUCTIONS = {
    "person": (
        "Update the existing note with new information. "
        "Keep confirmed facts. Update the 'Current Role & Work' section with anything new. "
        "Add new items to 'Notable Contributions' and 'Controversies' if found. "
        "Do not delete content unless it is clearly outdated or wrong."
    ),
    "tech": (
        "Update 'Current Status' with the latest version and release info. "
        "Add new use cases or ecosystem entries if found. "
        "Keep the core architecture explanation unless something fundamental changed. "
        "Flag deprecated features or removed APIs."
    ),
    "event": (
        "Add any new outcomes or aftereffects that have emerged since the last research. "
        "Update the 'Aftermath' section. Do not rewrite history — append to the timeline."
    ),
    "concept": (
        "Refine the definition if new clarity exists. Add to 'Applications' if new use cases found. "
        "Add to 'Criticisms' if new counter-arguments exist."
    ),
    "research": (
        "Update 'Key Facts' and 'Details' with new findings. "
        "Move superseded information to a clearly marked subsection. "
        "Add newly discovered open questions."
    ),
}

# ── Conflict instruction (injected into all prompts) ─────────────────────────

_CONFLICT_INSTRUCTION = """\
IMPORTANT — Conflict Detection:
If any new finding directly contradicts something in the existing note, insert an Obsidian callout immediately after the conflicting statement in your output:

> [!warning] Potential Conflict
> Existing note states: "..."
> New research suggests: "..."

Do not silently overwrite contradictions — always flag them."""

# ── WikiLink instruction ──────────────────────────────────────────────────────

_WIKILINK_INSTRUCTION = """\
WikiLinks:
When referencing related topics, people, technologies, or events by name, wrap them in [[double brackets]].
Example: "The work of [[Alan Turing]] influenced [[Computer Science]]."
Only use WikiLinks for topics that deserve their own research note — not for every noun."""

# ── Depth-specific research modes ────────────────────────────────────────────

_DEPTH_MODES = {
    0: (
        "DEPTH 0 — Cold Start",
        "This topic has never been researched. Build a solid overview from scratch. "
        "Find the most authoritative and widely cited sources. Prioritize breadth — "
        "cover all the major sections. Do at least 2 web searches and fetch 2-3 pages."
    ),
    1: (
        "DEPTH 1 — Verify & Expand",
        "The topic has a basic note. Now verify the key claims with additional sources. "
        "Look for anything that's changed recently. Expand thin sections. "
        "Check if any facts are disputed or outdated. Add at least one source you haven't used before."
    ),
    2: (
        "DEPTH 2 — Cross-Link & Connect",
        "The topic is well-documented. Now focus on connections. "
        "How does this topic relate to other topics in the vault? "
        "Add WikiLinks to related concepts, people, and events. "
        "Look for non-obvious connections. Search for the topic in combination with adjacent subjects."
    ),
}

_DEPTH_POWERSEARCH = (
    "DEPTH 3+ — Powersearch",
    "This topic has been thoroughly researched at surface level. Now go deep. "
    "Search for academic papers, primary sources, and minority viewpoints. "
    "Follow citation trails — if a source references another source, fetch it. "
    "Look for contradictions in the existing note and try to resolve them. "
    "Search for the topic combined with terms like: 'study', 'research', 'analysis', "
    "'criticism', 'alternative view', 'history', 'origin'. "
    "Prioritize sources with credibility scores of 1 or 2 (academic/government/quality-news)."
)


def get_depth_instruction(depth: int) -> tuple[str, str]:
    """Return (mode_label, mode_instruction) for the given research depth."""
    if depth >= 3:
        return _DEPTH_POWERSEARCH
    return _DEPTH_MODES.get(depth, _DEPTH_MODES[0])


# ── Public API ────────────────────────────────────────────────────────────────

def get_research_prompt(topic_type: str, topic_name: str, existing_note_body: str = "",
                        depth: int = 0) -> str:
    t = topic_type if topic_type in _SECTIONS_BY_TYPE else "research"
    sections = _SECTIONS_BY_TYPE[t]
    update_instructions = _UPDATE_INSTRUCTIONS[t]
    depth_label, depth_instruction = get_depth_instruction(depth)

    if existing_note_body.strip():
        existing_block = (
            f"EXISTING NOTE CONTENT (update this, do not start from scratch):\n"
            f"---\n{existing_note_body.strip()}\n---\n\n"
            f"Update instructions: {update_instructions}\n"
        )
    else:
        existing_block = "This is a new topic — no existing note. Research it from scratch.\n"

    prompt = f"""\
Research task: {topic_name}
Topic type: {t}
Research depth: {depth} — {depth_label}

{depth_instruction}

{existing_block}
Produce a complete updated note body using this exact section structure:

# {topic_name}

{sections}

{_CONFLICT_INSTRUCTION}

{_WIKILINK_INSTRUCTION}

When you have finished writing the note content, call update_note with:
- topic: "{topic_name}"
- body: the complete markdown body above (starting with # {topic_name})
- sources: comma-separated list of URLs you fetched

Research thoroughly before writing. Use web_search and fetch_page to gather current information.
Start by calling read_note to check what is already known, then search for updates."""

    return prompt


def get_update_instructions(topic_type: str) -> str:
    t = topic_type if topic_type in _UPDATE_INSTRUCTIONS else "research"
    return _UPDATE_INSTRUCTIONS[t]
