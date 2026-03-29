"""
Agent Roster — assign specific Ollama models to topic types or individual topics.
Persists assignments to agents.json.

Resolution order for get_model_for(note):
  1. Topic-specific assignment (note.slug in assigned_topics)
  2. Type-level assignment (note.type in assigned_types)
  3. agents.json default_model
  4. config.json ollama.model  ← final fallback
"""
import json
import os
from dataclasses import dataclass, field
from config import cfg

_DEFAULT_PATH = "agents.json"

_EMPTY_ROSTER = {
    "agents": [],
    "default_model": None,
}


@dataclass
class AgentEntry:
    model: str
    nickname: str = ""
    assigned_types: list = field(default_factory=list)
    assigned_topics: list = field(default_factory=list)
    capabilities: list = field(default_factory=list)  # e.g. ["coding", "creative", "uncensored"]
    system_prompt: str = ""  # custom persona prompt
    description: str = ""


class AgentRoster:
    def __init__(self, path: str = None):
        self._path = path or cfg.get("agents.path", _DEFAULT_PATH)
        self._agents: list[AgentEntry] = []
        self._default_model: str | None = None
        self.load()

    # ── Persistence ───────────────────────────────────────────────────────────

    def load(self) -> None:
        if not os.path.exists(self._path):
            self._agents = []
            self._default_model = None
            self.save()
            return
        with open(self._path, "r", encoding="utf-8") as f:
            data = json.load(f)
        self._default_model = data.get("default_model")
        self._agents = [
            AgentEntry(
                model=a["model"],
                nickname=a.get("nickname", ""),
                assigned_types=a.get("assigned_types", []),
                assigned_topics=a.get("assigned_topics", []),
                capabilities=a.get("capabilities", []),
                system_prompt=a.get("system_prompt", ""),
                description=a.get("description", ""),
            )
            for a in data.get("agents", [])
        ]

    def save(self) -> None:
        with open(self._path, "w", encoding="utf-8") as f:
            json.dump(
                {
                    "agents": [
                        {
                            "model": a.model,
                            "nickname": a.nickname,
                            "assigned_types": a.assigned_types,
                            "assigned_topics": a.assigned_topics,
                            "capabilities": a.capabilities,
                            "system_prompt": a.system_prompt,
                            "description": a.description,
                        }
                        for a in self._agents
                    ],
                    "default_model": self._default_model,
                },
                f,
                indent=2,
            )

    # ── CRUD ──────────────────────────────────────────────────────────────────

    def _get_or_create(self, model: str) -> AgentEntry:
        for a in self._agents:
            if a.model == model:
                return a
        entry = AgentEntry(model=model)
        self._agents.append(entry)
        return entry

    def assign_type(self, model: str, topic_type: str) -> None:
        entry = self._get_or_create(model)
        if topic_type not in entry.assigned_types:
            entry.assigned_types.append(topic_type)
        self.save()

    def assign_topic(self, model: str, topic_slug: str) -> None:
        entry = self._get_or_create(model)
        if topic_slug not in entry.assigned_topics:
            entry.assigned_topics.append(topic_slug)
        self.save()

    def add_capability(self, model: str, capability: str) -> None:
        entry = self._get_or_create(model)
        if capability not in entry.capabilities:
            entry.capabilities.append(capability)
        self.save()

    def set_system_prompt(self, model: str, prompt: str) -> None:
        entry = self._get_or_create(model)
        entry.system_prompt = prompt
        self.save()

    def set_default(self, model: str) -> None:
        self._default_model = model
        self.save()

    def clear(self, model: str) -> bool:
        for i, a in enumerate(self._agents):
            if a.model == model:
                self._agents.pop(i)
                self.save()
                return True
        return False

    def set_description(self, model: str, description: str) -> None:
        entry = self._get_or_create(model)
        entry.description = description
        self.save()

    def set_nickname(self, model: str, nickname: str) -> None:
        entry = self._get_or_create(model)
        entry.nickname = nickname
        self.save()

    # ── Model resolution ──────────────────────────────────────────────────────

    def get_model_for(self, note) -> str:
        slug = getattr(note, "slug", "")
        topic_type = getattr(note, "type", "")

        # 1. Exact topic slug match
        for agent in self._agents:
            if slug in agent.assigned_topics:
                return agent.model

        # 2. Topic type match
        for agent in self._agents:
            if topic_type in agent.assigned_types:
                return agent.model

        # 3. Roster-level default
        if self._default_model:
            return self._default_model

        # 4. config.json fallback
        return cfg.get("ollama.model")

    def get_system_prompt_for(self, model: str) -> str:
        for a in self._agents:
            if a.model == model:
                return a.system_prompt
        return ""

    # ── Inspection ────────────────────────────────────────────────────────────

    def list_available(self) -> list[dict]:
        from llm import list_models, OllamaConnectionError, get_loaded_models
        try:
            live_models = set(list_models())
        except (OllamaConnectionError, Exception):
            live_models = set()

        loaded_models = set(get_loaded_models())
        assigned_models = {a.model for a in self._agents}
        all_models = live_models | assigned_models

        result = []
        for model in all_models:
            entry = next((a for a in self._agents if a.model == model), None)
            result.append(
                {
                    "model": model,
                    "available": model in live_models,
                    "loaded": model in loaded_models,
                    "assigned_types": entry.assigned_types if entry else [],
                    "assigned_topics": entry.assigned_topics if entry else [],
                    "capabilities": entry.capabilities if entry else [],
                    "nickname": entry.nickname if entry else "",
                    "description": entry.description if entry else "",
                }
            )
        result.sort(key=lambda x: (not x["loaded"], x["model"]))
        return result

    def format_roster(self) -> str:
        rows = self.list_available()
        default = self._default_model or cfg.get("ollama.model")
        lines = [f"\nAgent Roster  (default: {default})", "=" * 56]

        if not rows:
            lines.append("  No models found. Is Ollama running?")
        else:
            for r in rows:
                status = "online" if r["available"] else "offline"
                if r["loaded"]:
                    status = "HOT/VRAM"
                nick = f" '{r['nickname']}'" if r["nickname"] else ""
                lines.append(f"\n  {r['model']}{nick}  [{status}]")
                if r["description"]:
                    lines.append(f"    desc   : {r['description']}")
                if r["capabilities"]:
                    lines.append(f"    caps   : {', '.join(r['capabilities'])}")
                if r["assigned_types"]:
                    lines.append(f"    types  : {', '.join(r['assigned_types'])}")
                if r["assigned_topics"]:
                    lines.append(f"    topics : {', '.join(r['assigned_topics'])}")

        lines.append(
            "\nUsage:\n"
            "  /agents assign <model> <type>        assign to topic type\n"
            "  /agents assign <model> topic:<slug>  assign to one topic\n"
            "  /agents clear <model>                remove all assignments\n"
        )
        return "\n".join(lines)


class CuratorAgent:
    """The 'Broker' agent that curates the right model for the job."""

    def __init__(self, roster: AgentRoster):
        self.roster = roster

    def recommend_agent(self, user_input: str, topic_context: str = "") -> str:
        """Ask a fast model to pick the best agent from the roster."""
        from llm import chat
        
        available = self.roster.list_available()
        if not available:
            return cfg.get("ollama.model")

        # Filter only available/online models
        online = [a for a in available if a["available"]]
        if not online:
            return cfg.get("ollama.model")

        broker_model = cfg.get("ollama.broker_model", "phi3:mini")
        
        # Build a list of model options for the broker to choose from
        options = []
        for a in online:
            opt = f"- {a['model']} (nick: {a['nickname'] or 'none'}, caps: {', '.join(a['capabilities']) or 'general'})"
            if a["loaded"]:
                opt += " [ALREADY LOADED IN VRAM]"
            options.append(opt)

        prompt = f"""
You are the Broker for a local AI research agent. Your job is to select the BEST local model for the user's request.

USER REQUEST: "{user_input}"
TOPIC CONTEXT: "{topic_context}"

AVAILABLE MODELS:
{chr(10).join(options)}

RULES:
1. Look for specialized CAPABILITIES first. If the request involves coding/technical work, pick a model with 'coding' or 'technical' caps.
2. If the request involves storytelling, creative writing, or roleplay, pick a model with 'creative' or 'roleplay' caps.
3. If the request is 'uncensored' or involves 'spicy' topics, pick a model with those specific capabilities or nicknames.
4. If no specialized model fits, or if the request is a general research question, pick the most capable general model or the one ALREADY LOADED in VRAM.
5. Output ONLY the exact model name string from the list. No explanation.

SELECTED MODEL:"""

        try:
            recommendation = chat([], prompt, stream=False, model=broker_model).strip()
            # Clean up potential markdown or extra text
            recommendation = recommendation.split("\n")[0].split(" ")[0].strip("`\"' ")
            
            # Verify it's actually in our online list
            for a in online:
                if recommendation == a["model"]:
                    return recommendation
            
            # Fallback to first loaded model or default
            for a in online:
                if a["loaded"]:
                    return a["model"]
            return online[0]["model"]
        except Exception:
            return cfg.get("ollama.model")
