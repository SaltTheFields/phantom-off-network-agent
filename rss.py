"""
RSS / Atom feed monitoring for Phantom topics.

Each topic note can have a `feeds:` list in its frontmatter — URLs of RSS/Atom feeds
to check before the LLM research loop. New items since last_researched are injected
into the agent context so the LLM works from fresh content instead of only web search.

Usage (automatic — called by scheduler before each topic):
    from rss import fetch_new_items
    items = fetch_new_items(note)  # returns list of FeedItem

Usage (manual in agent.py):
    /feeds add <topic> <url>   # not implemented here — edit note frontmatter directly
"""

import re
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

import requests


@dataclass
class FeedItem:
    title: str
    url: str
    summary: str
    published: Optional[str] = None   # ISO date string or ""
    feed_url: str = ""


# ── Minimal feed parser (no feedparser dep) ───────────────────────────────────

def _parse_feed(xml: str, feed_url: str) -> list[FeedItem]:
    """Parse RSS 2.0 or Atom feed XML. Returns list of FeedItem, newest first."""
    items: list[FeedItem] = []

    # Detect format
    is_atom = "<feed" in xml[:500]

    if is_atom:
        entries = re.findall(r"<entry>(.*?)</entry>", xml, re.DOTALL)
        for entry in entries:
            title = _tag(entry, "title")
            link_match = re.search(r'<link[^>]+href=["\']([^"\']+)["\']', entry)
            url = link_match.group(1) if link_match else _tag(entry, "link")
            summary = _tag(entry, "summary") or _tag(entry, "content")
            published = _tag(entry, "published") or _tag(entry, "updated")
            items.append(FeedItem(
                title=_strip_html(title),
                url=url.strip(),
                summary=_strip_html(summary)[:400],
                published=_normalize_date(published),
                feed_url=feed_url,
            ))
    else:
        # RSS 2.0
        entries = re.findall(r"<item>(.*?)</item>", xml, re.DOTALL)
        for entry in entries:
            title = _tag(entry, "title")
            url = _tag(entry, "link")
            summary = _tag(entry, "description")
            published = _tag(entry, "pubDate")
            items.append(FeedItem(
                title=_strip_html(title),
                url=url.strip(),
                summary=_strip_html(summary)[:400],
                published=_normalize_date(published),
                feed_url=feed_url,
            ))

    return items


def _tag(xml: str, tag: str) -> str:
    """Extract first occurrence of <tag>...</tag>, stripping CDATA."""
    m = re.search(rf"<{tag}[^>]*>(.*?)</{tag}>", xml, re.DOTALL | re.IGNORECASE)
    if not m:
        return ""
    text = m.group(1)
    # Strip CDATA
    cdata = re.match(r"<!\[CDATA\[(.*?)\]\]>", text, re.DOTALL)
    if cdata:
        return cdata.group(1).strip()
    return text.strip()


def _strip_html(text: str) -> str:
    """Remove HTML tags from text."""
    text = re.sub(r"<[^>]+>", "", text)
    text = re.sub(r"&amp;", "&", text)
    text = re.sub(r"&lt;", "<", text)
    text = re.sub(r"&gt;", ">", text)
    text = re.sub(r"&quot;", '"', text)
    text = re.sub(r"&#\d+;", "", text)
    return text.strip()


def _normalize_date(raw: str) -> str:
    """Try to parse a date string and return ISO format YYYY-MM-DD, or raw."""
    if not raw:
        return ""
    formats = [
        "%a, %d %b %Y %H:%M:%S %z",   # RFC 822
        "%a, %d %b %Y %H:%M:%S %Z",
        "%Y-%m-%dT%H:%M:%S%z",        # ISO 8601
        "%Y-%m-%dT%H:%M:%SZ",
        "%Y-%m-%d",
    ]
    for fmt in formats:
        try:
            dt = datetime.strptime(raw.strip(), fmt)
            return dt.strftime("%Y-%m-%d")
        except ValueError:
            continue
    # Try just extracting YYYY-MM-DD
    m = re.search(r"(\d{4}-\d{2}-\d{2})", raw)
    return m.group(1) if m else raw[:20]


# ── Public API ─────────────────────────────────────────────────────────────────

def fetch_feed(feed_url: str, timeout: int = 10) -> list[FeedItem]:
    """
    Fetch and parse a single RSS/Atom feed URL.
    Returns list of FeedItem (may be empty on error).
    """
    try:
        headers = {"User-Agent": "Mozilla/5.0 (compatible; phantom-research-agent/1.1)"}
        resp = requests.get(feed_url, timeout=timeout, headers=headers)
        resp.raise_for_status()
        return _parse_feed(resp.text, feed_url)
    except Exception:
        return []


def fetch_new_items(note, since_date: str = None) -> list[FeedItem]:
    """
    Fetch all feeds attached to a note and return items newer than since_date.

    since_date defaults to note.last_researched. If no feeds on the note, returns [].
    Items are deduplicated by URL and sorted newest first.
    """
    feeds = getattr(note, "feeds", []) or []
    if not feeds:
        return []

    cutoff = since_date or getattr(note, "last_researched", "") or ""

    all_items: list[FeedItem] = []
    seen_urls: set[str] = set()

    for feed_url in feeds:
        feed_url = feed_url.strip()
        if not feed_url:
            continue
        items = fetch_feed(feed_url)
        for item in items:
            if item.url in seen_urls:
                continue
            seen_urls.add(item.url)
            if cutoff and item.published and item.published < cutoff:
                continue  # older than last research — skip
            all_items.append(item)

    # Sort newest first
    all_items.sort(key=lambda x: x.published or "", reverse=True)
    return all_items


def format_feed_context(items: list[FeedItem], max_items: int = 10) -> str:
    """
    Format feed items as a context block to inject into the LLM prompt.
    """
    if not items:
        return ""

    shown = items[:max_items]
    lines = [
        f"## Recent feed items ({len(shown)} of {len(items)} new):",
        "",
    ]
    for item in shown:
        date_str = f" [{item.published}]" if item.published else ""
        lines.append(f"### {item.title}{date_str}")
        lines.append(f"URL: {item.url}")
        if item.summary:
            lines.append(item.summary)
        lines.append("")

    return "\n".join(lines)
