import re
import json
from tools import format_tools_for_prompt
from context import get_context

SYSTEM_PROMPT_TEMPLATE = """\
You are a private research assistant running locally on Ollama. You help with research, analysis, and information gathering. You have no access to personal accounts and all searches are privacy-preserving via DuckDuckGo.

## Your Tools
To use a tool, output ONLY a JSON block in this exact format — nothing before or after it on that section:

```json
{{"tool": "tool_name", "parameter1": "value1"}}
```

Available tools:

{tool_descriptions}

## How to Think and Act
1. Read the user's question carefully.
2. If the question requires current or external information, use web_search.
3. Before searching the web, check recall to see if you've researched this before.
4. After a web_search, use fetch_page on the most relevant result URL for full content.
5. After gathering information, synthesize a clear, well-cited answer.
6. If you learned a key fact worth keeping, use remember with relevant tags.
7. Always include source URLs when citing researched information.

## Rules
- Only use URLs that came from actual search results — never make up URLs.
- If a search returns nothing useful, say so and try a different query.
- Keep responses focused and practical.
- Output the JSON tool call block on its own — don't add text before or after the block in the same turn.
- After a tool result is shown to you, continue reasoning and either call another tool or give your final answer.

{memory_context_section}
"""


def build_system_prompt(memory_context: str = "", topic_context: str = "") -> str:
    tool_descriptions = format_tools_for_prompt()
    memory_section = f"## Context From Previous Sessions\n{memory_context}" if memory_context else ""

    static_ctx = get_context().strip()
    static_section = f"## Agent Context\n{static_ctx}" if static_ctx else ""

    topic_section = f"## Current Research Task\n{topic_context}" if topic_context else ""

    base = SYSTEM_PROMPT_TEMPLATE.format(
        tool_descriptions=tool_descriptions,
        memory_context_section=memory_section,
    )
    if static_section:
        base = base.rstrip() + "\n\n" + static_section + "\n"
    if topic_section:
        base = base.rstrip() + "\n\n" + topic_section + "\n"
    return base


def parse_tool_call(text: str) -> dict | None:
    """
    Extract a JSON tool call from LLM output.
    Tries multiple strategies to handle imperfect model output.
    Returns a dict with at least a 'tool' key, or None.
    """
    if not text:
        return None

    # Strategy 1: look for ```json ... ``` blocks
    pattern = r"```(?:json)?\s*(\{[^`]+\})\s*```"
    matches = re.findall(pattern, text, re.DOTALL)
    for candidate in matches:
        result = _try_parse(candidate)
        if result and "tool" in result:
            return result

    # Strategy 2: look for bare { "tool": ... } object
    pattern2 = r'\{\s*"tool"\s*:\s*"[^"]+".+?\}'
    matches2 = re.findall(pattern2, text, re.DOTALL)
    for candidate in matches2:
        result = _try_parse(candidate)
        if result and "tool" in result:
            return result

    # Strategy 3: find outermost { } block containing "tool"
    if '"tool"' in text:
        start = text.find("{")
        end = text.rfind("}") + 1
        if start != -1 and end > start:
            result = _try_parse(text[start:end])
            if result and "tool" in result:
                return result

    return None


def _try_parse(text: str) -> dict | None:
    text = text.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    # Try fixing common issues: trailing commas, single quotes
    fixed = re.sub(r",\s*([}\]])", r"\1", text)  # trailing commas
    fixed = fixed.replace("'", '"')               # single → double quotes
    try:
        return json.loads(fixed)
    except json.JSONDecodeError:
        return None
