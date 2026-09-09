import json
import logging
import requests
from pathlib import Path
from typing import Callable, Optional

from or_client import client as openrouter_client

logger = logging.getLogger("llm_client")

def _get_base_dir() -> Path:
    import sys
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent

BASE_DIR = _get_base_dir()
SETTINGS_PATH = BASE_DIR / "config" / "app_settings.json"

# Canonical provider identifiers used across the app ("Gemini", "OpenRouter", "Local").
DEFAULT_PROVIDER = "OpenRouter"
PROVIDER_ALIASES = {
    "gemini": "Gemini",
    "google gemini": "Gemini",
    "openrouter": "OpenRouter",
    "local": "Local",
    "ollama": "Local",
    "ollama (local)": "Local",
    "lm studio": "Local",
}
LOCAL_CONNECT_TIMEOUT = 10.0   # seconds to establish a connection to the local AI server
LOCAL_READ_TIMEOUT    = 120.0  # seconds to wait for the full local completion


def normalize_provider(raw: object) -> str:
    """Map user-facing provider labels to the canonical identifier."""
    key = str(raw or "").strip().lower()
    return PROVIDER_ALIASES.get(key, key.capitalize() or DEFAULT_PROVIDER)


class UnifiedAIClient:
    """Single AI-provider facade.

    Providers:
      - "Local" -> Ollama / LM Studio OpenAI-compatible endpoint
                   (offline-first local provider)
      - "OpenRouter" / "Gemini" -> remote OpenAI-compatible routing

    When ``auto_provider_switch`` is enabled in app settings and the active
    provider fails, the client tries the alternate class of provider and then
    raises a precise, honest error if both are unavailable. It never fakes a
    successful answer.
    """

    def __init__(self):
        self._provider = DEFAULT_PROVIDER
        self._local_url = "http://localhost:11434/v1"
        self._local_model = "llama3.2"
        self._auto_switch = True
        self.reload_settings()

    def reload_settings(self):
        try:
            with open(SETTINGS_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
            self._provider = normalize_provider(data.get("default_ai_provider", DEFAULT_PROVIDER))
            self._local_url = str(data.get("local_ai_url", "http://localhost:11434/v1")).rstrip("/")
            self._local_model = str(data.get("local_ai_model", "llama3.2") or "llama3.2")
            self._auto_switch = bool(data.get("auto_provider_switch", True))
        except Exception as e:
            logger.error(f"[LLM Client] Failed to load settings: {e}")

    # --- helpers -----------------------------------------------------------

    def _is_local_provider(self) -> bool:
        return self._provider == "Local"

    def _ollama_label(self) -> str:
        return "OLLAMA UNAVAILABLE" if "11434" in self._local_url else "LOCAL AI UNAVAILABLE"

    def _local_chat_completion(self, messages: list[dict], temperature: float = 0.7, response_format: Optional[dict] = None) -> Optional[str]:
        payload = {
            "model": self._local_model,
            "messages": messages,
            "temperature": temperature
        }
        if response_format:
            payload["response_format"] = response_format

        endpoint = f"{self._local_url}/chat/completions"
        try:
            resp = requests.post(
                endpoint,
                headers={"Content-Type": "application/json"},
                json=payload,
                timeout=(LOCAL_CONNECT_TIMEOUT, LOCAL_READ_TIMEOUT),
            )
            if resp.status_code == 200:
                data = resp.json()
                content = data.get("choices", [{}])[0].get("message", {}).get("content", "")
                return content.strip() if content else None
            else:
                logger.error(f"[LLM Client] Local AI Error {resp.status_code}: {resp.text[:300]}")
                return None
        except requests.exceptions.ConnectionError:
            logger.error(f"[LLM Client] {self._ollama_label()} — could not reach {endpoint}")
            return None
        except Exception as e:
            logger.error(f"[LLM Client] Local AI Request Failed: {e}")
            return None

    def _clean_json(self, raw: str) -> dict:
        clean = raw.strip()
        if clean.startswith("```"):
            parts = clean.split("```")
            clean = parts[1] if len(parts) > 1 else clean
            if clean.startswith("json"):
                clean = clean[4:]
        clean = clean.strip().rstrip("`").strip()
        try:
            return json.loads(clean)
        except json.JSONDecodeError as e:
            raise ValueError(f"Local model returned unparseable JSON: {e}\nRaw output: {raw[:200]}")

    def _try_alternate_or_raise(self, primary_label: str, primary_err: Exception,
                                alternate_fn: Callable[[], object], alternate_label: str) -> object:
        """Run the alternate provider once (if auto-switch enabled), else raise honestly."""
        if not self._auto_switch:
            raise RuntimeError(f"{primary_label} failed: {primary_err}") from primary_err
        try:
            result = alternate_fn()
            if result:
                return result
            raise RuntimeError(f"{alternate_label} returned an empty response")
        except Exception as alt_err:
            raise RuntimeError(
                f"AI UNAVAILABLE — {primary_label} failed ({primary_err}); "
                f"fallback {alternate_label} failed ({alt_err}). "
                f"Check config/api_keys.json and that the local AI server is running."
            ) from alt_err

    # --- public API --------------------------------------------------------

    def chat(self, prompt: str, system: str = "You are a helpful assistant.", history: Optional[list[dict]] = None, model: Optional[str] = None, max_tokens: int = 4096, temperature: float = 0.7) -> str:
        self.reload_settings()
        messages = [{"role": "system", "content": system}]
        if history:
            messages.extend(history)
        messages.append({"role": "user", "content": prompt})

        if self._is_local_provider():
            result = self._local_chat_completion(messages, temperature)
            if result:
                return result
            err = RuntimeError(
                f"{self._ollama_label()} — check that Ollama/LM Studio is running at {self._local_url}"
            )
            alt = self._try_alternate_or_raise(
                self._ollama_label(), err,
                lambda: openrouter_client.chat(prompt, system, history, model, max_tokens, temperature),
                "OpenRouter",
            )
            return alt  # type: ignore[return-value]
        else:
            try:
                return openrouter_client.chat(prompt, system, history, model, max_tokens, temperature)
            except Exception as e:
                alt = self._try_alternate_or_raise(
                    f"{self._provider} provider", e,
                    lambda: self._local_chat_completion(messages, temperature),
                    self._ollama_label(),
                )
                if alt:
                    return alt  # type: ignore[return-value]
                raise RuntimeError(f"{self._provider} provider failed: {e}") from e

    def chat_json(self, prompt: str, system: str = "Return ONLY valid JSON.", model: Optional[str] = None, max_tokens: int = 4096) -> dict:
        self.reload_settings()
        messages = [
            {"role": "system", "content": system + " Output valid JSON only, without any markdown formatting."},
            {"role": "user", "content": prompt}
        ]

        def _local_raw() -> Optional[str]:
            return self._local_chat_completion(messages, temperature=0.2, response_format={"type": "json_object"})

        def _local_json() -> Optional[dict]:
            raw = _local_raw()
            return self._clean_json(raw) if raw else None

        if self._is_local_provider():
            raw = _local_raw()
            if raw:
                return self._clean_json(raw)
            err = RuntimeError(
                f"{self._ollama_label()} — check that Ollama/LM Studio is running at {self._local_url}"
            )
            alt = self._try_alternate_or_raise(
                self._ollama_label(), err,
                lambda: openrouter_client.chat_json(prompt, system, model, max_tokens),
                "OpenRouter",
            )
            return alt  # type: ignore[return-value]
        else:
            try:
                return openrouter_client.chat_json(prompt, system, model, max_tokens)
            except Exception as e:
                alt = self._try_alternate_or_raise(
                    f"{self._provider} provider", e,
                    lambda: _local_json(),
                    self._ollama_label(),
                )
                if alt:
                    return alt  # type: ignore[return-value]
                raise RuntimeError(f"{self._provider} provider failed: {e}") from e

    def vision(self, prompt: str, image_b64: str, mime: str = "image/png", system: str = "Analyze the image.", model: Optional[str] = None, max_tokens: int = 1024) -> str:
        self.reload_settings()
        if self._is_local_provider():
            messages = [
                {"role": "system", "content": system},
                {
                    "role": "user",
                    "content": [
                        {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{image_b64}"}},
                        {"type": "text", "text": prompt}
                    ]
                }
            ]
            result = self._local_chat_completion(messages, temperature=0.2)
            if result:
                return result
            raise RuntimeError(
                f"{self._ollama_label()} — vision request failed. Check that Ollama/LM Studio is running "
                f"with a multimodal model at {self._local_url}."
            )
        else:
            return openrouter_client.vision(prompt, image_b64, mime, system, model, max_tokens)

    def vision_from_file(self, prompt: str, image_path: str, system: str = "Analyze the image.", model: Optional[str] = None, max_tokens: int = 1024) -> str:
        self.reload_settings()
        if self._is_local_provider():
            import base64
            path = Path(image_path)
            mime_map = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".webp": "image/webp", ".gif": "image/gif"}
            mime = mime_map.get(path.suffix.lower(), "image/png")
            with open(path, "rb") as f:
                image_b64 = base64.b64encode(f.read()).decode("utf-8")
            return self.vision(prompt, image_b64, mime, system, model, max_tokens)
        else:
            return openrouter_client.vision_from_file(prompt, image_path, system, model, max_tokens)

    def multi_turn(self, messages: list[dict], model: Optional[str] = None, max_tokens: int = 4096, temperature: float = 0.7) -> str:
        self.reload_settings()
        if self._is_local_provider():
            result = self._local_chat_completion(messages, temperature)
            if result:
                return result
            raise RuntimeError(f"{self._ollama_label()} — check that Ollama/LM Studio is running at {self._local_url}")
        else:
            return openrouter_client.multi_turn(messages, model, max_tokens, temperature)


client = UnifiedAIClient()
