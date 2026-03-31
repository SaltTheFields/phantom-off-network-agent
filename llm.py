import sys
import ollama as _ollama
from config import cfg


class OllamaConnectionError(Exception):
    pass


def check_connection() -> tuple[bool, str]:
    base_url = cfg.get("ollama.base_url")
    try:
        client = _ollama.Client(host=base_url)
        client.list()
        return True, f"Connected to Ollama at {base_url}"
    except Exception as e:
        return False, (
            f"Cannot reach Ollama at {base_url}\n"
            f"  - Is the gaming PC on?\n"
            f"  - Is Ollama running? (start with: OLLAMA_HOST=0.0.0.0 ollama serve)\n"
            f"  - Is the base_url correct in config.json?\n"
            f"  Error: {e}"
        )


def list_models() -> list[str]:
    base_url = cfg.get("ollama.base_url")
    try:
        client = _ollama.Client(host=base_url)
        response = client.list()
        return [m.model for m in response.models if "embed" not in m.model.lower()]
    except Exception as e:
        raise OllamaConnectionError(f"Could not list models: {e}")


def get_loaded_models() -> list[str]:
    """Check which models are currently loaded in VRAM via the ps/ endpoint."""
    import requests
    base_url = cfg.get("ollama.base_url", "http://localhost:11434")
    try:
        # Ollama doesn't have a direct 'ps' in the python lib yet, use requests
        resp = requests.get(f"{base_url}/api/ps", timeout=5)
        if resp.status_code == 200:
            data = resp.json()
            return [m["name"] for m in data.get("models", [])]
        return []
    except Exception:
        return []


def chat(messages: list[dict], system_prompt: str, stream: bool = True, model: str = None) -> str:
    import time as _time
    base_url = cfg.get("ollama.base_url")
    model = model or cfg.get("ollama.model")
    timeout = cfg.get("ollama.timeout", 120)
    temperature = cfg.get("ollama.temperature", 0.7)
    max_retries = cfg.get("ollama.chat_retries", 2)  # retry on timeout before giving up

    ollama_messages = [{"role": "system", "content": system_prompt}] + messages

    last_exc = None
    for attempt in range(max_retries):
        try:
            client = _ollama.Client(host=base_url, timeout=timeout)

            if stream:
                full_response = ""
                response_stream = client.chat(
                    model=model,
                    messages=ollama_messages,
                    stream=True,
                    options={"temperature": temperature},
                )
                for chunk in response_stream:
                    token = chunk.message.content
                    if token:
                        print(token, end="", flush=True)
                        full_response += token
                print()  # newline after streamed response
                return full_response
            else:
                response = client.chat(
                    model=model,
                    messages=ollama_messages,
                    stream=False,
                    options={"temperature": temperature},
                )
                return response.message.content

        except Exception as e:
            last_exc = e
            err_str = str(e).lower()
            is_timeout = "timeout" in err_str or "readtimeout" in err_str or "timed out" in err_str
            is_conn_err = "connection" in err_str or "refused" in err_str

            if is_timeout and attempt < max_retries - 1:
                backoff = 15 * (attempt + 1)  # 15s, 30s, ...
                print(f"\n  [llm] timeout on attempt {attempt + 1}/{max_retries} — retrying in {backoff}s", flush=True)
                _time.sleep(backoff)
                continue

            if is_timeout or is_conn_err:
                raise OllamaConnectionError(
                    f"Lost connection to Ollama at {base_url} after {attempt + 1} attempt(s): {e}"
                )
            raise

    # All retries exhausted
    raise OllamaConnectionError(
        f"Ollama at {base_url} timed out after {max_retries} attempt(s): {last_exc}"
    )
