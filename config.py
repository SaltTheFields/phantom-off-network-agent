import json
import os

_DEFAULTS = {
    "ollama": {
        "base_url": "http://localhost:11434",
        "model": "llama3.2",
        "chat_model": "llama3.1:8b",
        "timeout": 120,
        "temperature": 0.7,
        "context_window": 4096,
    },
    "memory": {
        "db_path": "data/memory.db",
        "max_short_term_messages": 20,
        "max_long_term_results": 5,
        "auto_save_threshold": 10,
    },
    "agent": {
        "max_iterations": 8,
        "verbose": False,
    },
    "search": {
        "max_results": 5,
        "fetch_timeout": 15,
    },
    "vault": {
        "path": "vault",
        "default_refresh_interval_days": 7,
        "conflict_detection": True,
    },
    "schedule": {
        "max_topics_per_run": 10,
        "stale_check_enabled": True,
        "generate_daily_digest": True,
        "silent_mode": True,
        "max_parallel_workers": 2,
        "depth_bias": 0.3,
        "depth_soft_cap": 5,
    },
    "context": {
        "path": "context.md",
    },
    "agents": {
        "path": "agents.json",
    },
    "logging": {
        "enabled": True,
        "log_dir": "logs",
        "level": "INFO",
        "max_log_age_days": 30,
    },
}


def _deep_merge(base: dict, override: dict) -> dict:
    result = dict(base)
    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def load_config(path: str = "config.json") -> dict:
    config = dict(_DEFAULTS)
    if os.path.exists(path):
        with open(path, "r") as f:
            user_config = json.load(f)
        config = _deep_merge(config, user_config)
    return config


class _Config:
    def __init__(self):
        self._data = load_config()

    def get(self, key_path: str, default=None):
        parts = key_path.split(".")
        node = self._data
        for part in parts:
            if not isinstance(node, dict) or part not in node:
                return default
            node = node[part]
        return node

    def set(self, key_path: str, value):
        parts = key_path.split(".")
        node = self._data
        for part in parts[:-1]:
            node = node.setdefault(part, {})
        node[parts[-1]] = value

    def reload(self):
        self._data = load_config()


cfg = _Config()
