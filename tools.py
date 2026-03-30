import re
import time
import requests
from datetime import datetime
from urllib.parse import urlparse
from config import cfg


def _scheme_variants(url: str) -> list[str]:
    """Return [original_url, scheme-flipped_url] so we try both http and https."""
    if url.startswith("https://"):
        return [url, "http://" + url[8:]]
    elif url.startswith("http://"):
        return [url, "https://" + url[7:]]
    return [url]


# ── Domain credibility tiers ──────────────────────────────────────────────────
# Returns (score 1-5, tier label)
# 1 = highest credibility, 5 = lowest

_ACADEMIC_DOMAINS = {
    ".edu", ".ac.uk", ".ac.au", ".ac.nz", ".ac.in", ".ac.jp",
    ".edu.au", ".edu.cn", ".uni-", "arxiv.org", "pubmed.ncbi.nlm.nih.gov",
    "scholar.google", "jstor.org", "researchgate.net", "semanticscholar.org",
    "ncbi.nlm.nih.gov", "nature.com", "sciencedirect.com", "springer.com",
    "ieee.org", "acm.org", "biorxiv.org", "medrxiv.org",
}

_GOV_DOMAINS = {".gov", ".gov.uk", ".gov.au", ".gov.ca", ".mil"}

_QUALITY_NEWS = {
    "reuters.com", "apnews.com", "bbc.com", "bbc.co.uk", "npr.org",
    "theguardian.com", "nytimes.com", "wsj.com", "ft.com", "economist.com",
    "scientificamerican.com", "newscientist.com", "arstechnica.com",
    "wired.com", "technologyreview.com", "theatlantic.com",
}

_ORG_DOMAINS = {".org"}

_LOW_QUALITY = {
    "reddit.com", "quora.com", "yahoo.com", "buzzfeed.com",
    "huffpost.com", "medium.com", "substack.com",
}

_SOCIAL_MEDIA = {
    "twitter.com", "x.com", "facebook.com", "instagram.com",
    "tiktok.com", "linkedin.com", "pinterest.com",
}


def score_domain(url: str) -> tuple[int, str]:
    """
    Score a URL's source credibility.
    Returns (score, label) where score 1=highest, 5=lowest.
    """
    try:
        parsed = urlparse(url)
        domain = parsed.netloc.lower().lstrip("www.")
    except Exception:
        return 3, "unknown"

    # Tier 1: academic / government
    for pat in _ACADEMIC_DOMAINS:
        if pat in domain:
            return 1, "academic"
    for pat in _GOV_DOMAINS:
        if domain.endswith(pat):
            return 1, "government"

    # Tier 2: quality journalism
    if domain in _QUALITY_NEWS:
        return 2, "quality-news"

    # Tier 3: .org and general reference
    if domain.endswith(".org"):
        return 3, "organization"
    if "wikipedia.org" in domain:
        return 3, "wikipedia"

    # Tier 4: social / aggregator / blogs
    if domain in _LOW_QUALITY:
        return 4, "aggregator"
    if domain in _SOCIAL_MEDIA:
        return 5, "social-media"

    # Default: general web
    return 3, "general-web"


# ── Retry helper ──────────────────────────────────────────────────────────────

def _retry(fn, max_retries: int = 3, base_delay: float = 1.0, exceptions=(Exception,)):
    """
    Call fn(), retrying up to max_retries times on any exception in `exceptions`.
    Uses exponential backoff: 1s, 2s, 4s, ...
    Raises the last exception if all retries exhausted.
    """
    last_exc = None
    for attempt in range(max_retries):
        try:
            return fn()
        except exceptions as e:
            last_exc = e
            if attempt < max_retries - 1:
                time.sleep(base_delay * (2 ** attempt))
    raise last_exc

TOOL_REGISTRY = [
    {
        "name": "web_search",
        "description": (
            "Search the web via DuckDuckGo. Use for current events, facts you don't know, "
            "or finding sources. Returns titles, URLs, and snippets."
        ),
        "parameters": {
            "query": "string — the search query",
            "max_results": "int (optional, default 5) — number of results to return",
        },
        "example": '{"tool": "web_search", "query": "rust async ecosystem 2025"}',
    },
    {
        "name": "fetch_page",
        "description": (
            "Fetch and read the text content of a URL. Strips HTML, ads, and navigation. "
            "Use after web_search to read a full article."
        ),
        "parameters": {
            "url": "string — full URL to fetch",
        },
        "example": '{"tool": "fetch_page", "url": "https://example.com/article"}',
    },
    {
        "name": "remember",
        "description": (
            "Save an important fact or summary to long-term memory. "
            "Use when you learn something worth keeping across sessions."
        ),
        "parameters": {
            "content": "string — the fact or summary to remember",
            "tags": "string — comma-separated keywords (e.g. 'python,async,tutorial')",
        },
        "example": '{"tool": "remember", "content": "tokio 1.x is the dominant async runtime in Rust", "tags": "rust,async,tokio"}',
    },
    {
        "name": "recall",
        "description": (
            "Search long-term memory for previously saved facts. "
            "Use when the user asks about something you may have researched before."
        ),
        "parameters": {
            "query": "string — keywords to search memory",
        },
        "example": '{"tool": "recall", "query": "python asyncio"}',
    },
    {
        "name": "read_note",
        "description": (
            "Read an existing research note from the vault by topic name or slug. "
            "Use before updating a topic to see what is already known."
        ),
        "parameters": {
            "topic": "string — topic name or slug to read",
        },
        "example": '{"tool": "read_note", "topic": "Python asyncio"}',
    },
    {
        "name": "update_note",
        "description": (
            "Write updated content to a vault note. "
            "Provide the full markdown body starting with # Heading. "
            "Include [[WikiLinks]] to related topics."
        ),
        "parameters": {
            "topic": "string — topic name or slug",
            "body": "string — full new markdown body for the note",
            "sources": "string (optional) — comma-separated URLs used in this research",
        },
        "example": '{"tool": "update_note", "topic": "Python asyncio", "body": "# Python asyncio\\n\\n..."}',
    },
]


def format_tools_for_prompt() -> str:
    lines = []
    for tool in TOOL_REGISTRY:
        lines.append(f"### {tool['name']}")
        lines.append(tool["description"])
        lines.append("Parameters:")
        for param, desc in tool["parameters"].items():
            lines.append(f"  - {param}: {desc}")
        lines.append(f"Example: `{tool['example']}`")
        lines.append("")
    return "\n".join(lines)


def web_search(query: str, max_results: int = None) -> str:
    n = max_results or cfg.get("search.max_results", 5)

    def _do_search():
        from ddgs import DDGS
        with DDGS() as ddgs:
            return list(ddgs.text(query, max_results=n))

    try:
        results = _retry(_do_search, max_retries=3, base_delay=1.0)

        if not results:
            return f"No results found for: {query}"

        lines = [f"Search results for: {query}\n"]
        for i, r in enumerate(results, 1):
            url = r.get("href", "")
            score, tier = score_domain(url)
            lines.append(f"{i}. {r.get('title', 'No title')}  [credibility: {tier} ({score}/5)]")
            lines.append(f"   URL: {url}")
            lines.append(f"   {r.get('body', '')[:200]}")
            lines.append("")
        return "\n".join(lines)
    except Exception as e:
        return f"Search failed: {e}"


def fetch_page(url: str) -> str:
    timeout = cfg.get("search.fetch_timeout", 15)
    max_chars = 4000

    if not url.startswith(("http://", "https://")):
        return f"Invalid URL (must start with http:// or https://): {url}"

    score, tier = score_domain(url)
    cred_note = f"[source credibility: {tier} ({score}/5)]"

    # ── Check article cache first ──────────────────────────────────────────
    try:
        from article_cache import get_cached, save_cache
        cached = get_cached(url)
        if cached:
            age_h = (datetime.now() - datetime.fromisoformat(cached["fetched_at"])).total_seconds() / 3600
            cache_note = f"[cached {age_h:.1f}h ago, fetch #{cached['fetch_count']}]"
            return _truncate(cached["content"], max_chars, url, f"{cred_note} {cache_note}")
    except Exception:
        save_cache = None

    # ── Fetch helpers ──────────────────────────────────────────────────────
    headers = {"User-Agent": "Mozilla/5.0 (compatible; research-agent/1.0)"}

    def _do_fetch(target_url: str) -> str:
        resp = requests.get(target_url, timeout=timeout, headers=headers)
        resp.raise_for_status()
        return resp.text

    def _extract(html: str) -> str:
        try:
            import trafilatura
            text = trafilatura.extract(html, include_links=False, include_images=False)
            if text and len(text.strip()) > 100:
                return text
        except ImportError:
            pass
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(html, "lxml")
        for tag in soup(["script", "style", "nav", "footer", "header", "aside"]):
            tag.decompose()
        text = soup.get_text(separator="\n")
        text = re.sub(r"\n{3,}", "\n\n", text)
        return re.sub(r"[ \t]+", " ", text).strip()

    # ── Try original URL with retries, then flip scheme ────────────────────
    last_err = None
    for try_url in _scheme_variants(url):
        try:
            html = _retry(
                lambda u=try_url: _do_fetch(u),
                max_retries=3,
                base_delay=1.5,
                exceptions=(requests.exceptions.Timeout, requests.exceptions.ConnectionError),
            )
            text = _extract(html)

            # Save to cache and annotate if content changed
            extra_note = ""
            try:
                if save_cache:
                    result = save_cache(try_url, text)
                    if result["fetch_count"] > 1 and result["changed"]:
                        extra_note = f" [UPDATED: {result['diff_summary']}]"
                    elif result["fetch_count"] > 1:
                        extra_note = f" [unchanged, fetch #{result['fetch_count']}]"
            except Exception:
                pass

            scheme_note = f" [via {try_url.split('://')[0]}]" if try_url != url else ""
            return _truncate(text, max_chars, try_url, f"{cred_note}{scheme_note}{extra_note}")

        except requests.exceptions.HTTPError as e:
            last_err = e
            continue
        except requests.exceptions.Timeout:
            last_err = Exception(f"timed out after 3 attempts (>{timeout}s each)")
            continue
        except Exception as e:
            last_err = e
            continue

    return f"Failed to fetch {url}: {last_err}"


def _truncate(text: str, max_chars: int, url: str, cred_note: str = "") -> str:
    header = f"[Content from {url}] {cred_note}".rstrip()
    if len(text) <= max_chars:
        return f"{header}\n\n{text}"
    return f"{header} — truncated to {max_chars} chars\n\n{text[:max_chars]}..."


def execute_tool(tool_call: dict, memory_store, vault=None, topics=None) -> str:
    name = tool_call.get("tool", "")

    try:
        if name == "web_search":
            query = tool_call.get("query", "")
            if not query:
                return "Error: web_search requires a 'query' parameter"
            max_r = tool_call.get("max_results")
            return web_search(query, max_results=int(max_r) if max_r else None)

        elif name == "fetch_page":
            url = tool_call.get("url", "")
            if not url:
                return "Error: fetch_page requires a 'url' parameter"
            return fetch_page(url)

        elif name == "remember":
            content = tool_call.get("content", "")
            if not content:
                return "Error: remember requires a 'content' parameter"
            tags = tool_call.get("tags", "")
            source_url = tool_call.get("source_url", "")
            fact_id = memory_store.save_fact(content, tags=tags, source_url=source_url)
            return f"Saved to memory (id={fact_id}): {content[:80]}{'...' if len(content) > 80 else ''}"

        elif name == "recall":
            query = tool_call.get("query", "")
            if not query:
                return "Error: recall requires a 'query' parameter"
            results = memory_store.search_facts(query)
            if not results:
                return f"No memories found matching: {query}"
            lines = [f"Memory search results for '{query}':"]
            for r in results:
                date = r["created_at"][:10] if r["created_at"] else "?"
                lines.append(f"  [{r['id']}] ({date}) {r['content']}")
                if r.get("tags"):
                    lines.append(f"    tags: {r['tags']}")
            return "\n".join(lines)

        elif name == "read_note":
            if vault is None:
                return "Vault not available in this mode."
            topic = tool_call.get("topic", "")
            if not topic:
                return "Error: read_note requires a 'topic' parameter"
            if topics:
                note = topics.get_topic(topic)
            else:
                slug = vault.name_to_slug(topic)
                note = vault.read_note(slug)
            if not note:
                return f"No note found for topic: '{topic}'"
            return f"[Note: {note.name}]\nStatus: {note.status} | Type: {note.type} | Last researched: {note.last_researched or 'never'}\n\n{note.body}"

        elif name == "update_note":
            if vault is None:
                return "Vault not available in this mode."
            topic = tool_call.get("topic", "")
            body = tool_call.get("body", "")
            if not topic or not body:
                return "Error: update_note requires 'topic' and 'body' parameters"

            if topics:
                note = topics.get_topic(topic)
            else:
                slug = vault.name_to_slug(topic)
                note = vault.read_note(slug)

            if note is None:
                # Auto-create if it doesn't exist
                slug = vault.name_to_slug(topic)
                from vault import Note
                from datetime import date
                note = Note(slug=slug, name=topic, body=body)
                note.created = str(date.today())
            else:
                note.body = body

            # Record sources with credibility score
            source_str = tool_call.get("sources", "")
            if source_str and memory_store:
                for url in [u.strip() for u in source_str.split(",") if u.strip()]:
                    cred_score, _ = score_domain(url)
                    memory_store.record_source(url, topic_slug=note.slug, reliability=cred_score)

            vault.write_note(note)
            if topics:
                topics.mark_researched(note.slug)
            vault.rebuild_index()
            vault.rebuild_backlinks()
            return f"Note updated: {note.name} ({note.slug}.md)"

        else:
            available = "web_search, fetch_page, remember, recall, read_note, update_note"
            return f"Unknown tool: '{name}'. Available: {available}"

    except Exception as e:
        return f"Tool '{name}' failed: {e}"
