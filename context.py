"""
Static context file manager.
Loads context.md once at startup and provides a cached read to every LLM call.
Thread-safe: after load_context() is called once in the main thread, get_context()
only reads an immutable string — safe to call from any thread.
"""
import os
from config import cfg

_DEFAULT_TEMPLATE = """\
# Phantom Agent — Static Context

## Research Goals
<!-- What should this agent focus on overall? -->
<!-- Example: "Track developments in AI, machine learning, and software engineering" -->

## Global Rules
- Always cite sources with direct URLs.
- Flag information older than 1 year as potentially outdated.
- Do not speculate beyond what sources confirm.
- Prefer primary sources (official docs, research papers, official announcements) over aggregators.
- When multiple sources conflict, note the discrepancy rather than choosing one.

## Domain Knowledge
<!-- Facts the agent should always know. Add project context, background, definitions. -->
<!-- Example: "This research focuses on the intersection of AI safety and policy." -->

## Avoid
<!-- Topics, source domains, or behaviors to skip. -->
- Do not fetch social media profile pages (Twitter, Facebook, Instagram, LinkedIn profiles).
- Do not treat press releases as objective fact — flag them as promotional.
"""

_context_cache: str | None = None


def _context_path() -> str:
    return cfg.get("context.path", "context.md")


def load_context() -> str:
    """
    Load context.md from disk. Creates default template if the file does not exist.
    Caches result in module-level _context_cache.
    Call once at startup from the main thread before spawning any workers.
    """
    global _context_cache
    path = _context_path()
    if not os.path.exists(path):
        with open(path, "w", encoding="utf-8") as f:
            f.write(_DEFAULT_TEMPLATE)
    with open(path, "r", encoding="utf-8") as f:
        _context_cache = f.read()
    return _context_cache


def get_context() -> str:
    """Return cached context string, loading on first call if needed."""
    global _context_cache
    if _context_cache is None:
        load_context()
    return _context_cache


def reload_context() -> str:
    """Force reload from disk, updating the cache. Returns new content."""
    global _context_cache
    _context_cache = None
    return load_context()
