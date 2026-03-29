import re
import requests
from config import cfg

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
    try:
        from ddgs import DDGS
        # Modern DDGS usage
        with DDGS() as ddgs:
            results = list(ddgs.text(query, max_results=n))
        
        if not results:
            return f"No results found for: {query}"
        
        lines = [f"Search results for: {query}\n"]
        for i, r in enumerate(results, 1):
            lines.append(f"{i}. {r.get('title', 'No title')}")
            lines.append(f"   URL: {r.get('href', '')}")
            lines.append(f"   {r.get('body', '')[:200]}")
            lines.append("")
        return "\n".join(lines)
    except Exception as e:
        return f"Search failed: {e}"


def fetch_page(url: str) -> str:
    timeout = cfg.get("search.fetch_timeout", 15)
    max_chars = 4000

    # Validate URL looks reasonable
    if not url.startswith(("http://", "https://")):
        return f"Invalid URL (must start with http:// or https://): {url}"

    try:
        headers = {"User-Agent": "Mozilla/5.0 (compatible; research-agent/1.0)"}
        resp = requests.get(url, timeout=timeout, headers=headers)
        resp.raise_for_status()
        html = resp.text

        # Try trafilatura first (best quality extraction)
        try:
            import trafilatura
            text = trafilatura.extract(html, include_links=False, include_images=False)
            if text and len(text.strip()) > 100:
                return _truncate(text, max_chars, url)
        except ImportError:
            pass

        # Fallback: BeautifulSoup tag stripping
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(html, "lxml")
        for tag in soup(["script", "style", "nav", "footer", "header", "aside"]):
            tag.decompose()
        text = soup.get_text(separator="\n")
        # Collapse excessive whitespace
        text = re.sub(r"\n{3,}", "\n\n", text)
        text = re.sub(r"[ \t]+", " ", text)
        return _truncate(text.strip(), max_chars, url)

    except requests.exceptions.Timeout:
        return f"Timed out fetching {url} (>{timeout}s)"
    except requests.exceptions.HTTPError as e:
        return f"HTTP error fetching {url}: {e}"
    except Exception as e:
        return f"Failed to fetch {url}: {e}"


def _truncate(text: str, max_chars: int, url: str) -> str:
    if len(text) <= max_chars:
        return f"[Content from {url}]\n\n{text}"
    return f"[Content from {url} — truncated to {max_chars} chars]\n\n{text[:max_chars]}..."


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

            # Record sources
            source_str = tool_call.get("sources", "")
            if source_str and memory_store:
                for url in [u.strip() for u in source_str.split(",") if u.strip()]:
                    memory_store.record_source(url, topic_slug=note.slug)

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
