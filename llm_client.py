import json
import logging
import requests
from pathlib import Path
from typing import Callable, Optional, Iterator

from or_client import client as openrouter_client
from omniroute import OmniRouteClient, OmniRouteUnavailable
from streaming import iter_sse_content

logger = logging.getLogger("llm_client")

def _get_base_dir() -> Path:
    import sys
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent

BASE_DIR = _get_base_dir()
SETTINGS_PATH = BASE_DIR / "config" / "app_settings.json"

# Canonical provider identifiers used across the app.
# Gemini and OpenRouter are cloud OpenAI-compatible routes; Local is Ollama /
# LM Studio; OmniRoute is the optional routing gateway in between.
DEFAULT_PROVIDER = "OpenRouter"
PROVIDER_ALIASES = {
    "gemini": "Gemini",
    "google gemini": "Gemini",
    "openrouter": "OpenRouter",
    "local": "Local",
    "ollama": "Local",
    "ollama (local)": "Local",
    "lm studio": "Local",
    "omniroute": "OmniRoute",
}
LOCAL_CONNECT_TIMEOUT = 10.0   # seconds to establish a connection to the local AI server
LOCAL_READ_TIMEOUT    = 120.0  # seconds to wait for the full local completion


def normalize_provider(raw: object) -> str:
    """Map user-facing provider labels to the canonical identifier."""
    key = str(raw or "").strip().lower()
    return PROVIDER_ALIASES.get(key, key.capitalize() or DEFAULT_PROVIDER)


class UnifiedAIClient:
    """Single AI-provider facade with an explicit routing chain.

    Request route (J.A.R.V.I.S. router):

        LOCAL OLLAMA  ->  OMNIROUTE (optional gateway)  ->  OPENROUTER/GEMINI

    The *default* provider is tried first. When ``auto_provider_switch`` is
    enabled, the rest of the chain is tried in the order above and the first
    successful provider wins. When every provider fails (or auto-switch is
    disabled) a precise, honest error is raised — the client NEVER fabricates
    a successful response.
    """

    def __init__(self):
        self._provider = DEFAULT_PROVIDER
        self._local_url = "http://localhost:11434/v1"
        self._local_model = "llama3.2"
        self._auto_switch = True
        self._omni = OmniRouteClient()
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
        self._omni.reload()

    # --- helpers -----------------------------------------------------------

    def _is_local_provider(self) -> bool:
        return self._provider == "Local"

    def _ollama_label(self) -> str:
        return "OLLAMA UNAVAILABLE" if "11434" in self._local_url else "LOCAL AI UNAVAILABLE"

    def _local_chat_completion(self, messages: list[dict], temperature: float = 0.7, response_format: Optional[dict] = None) -> Optional[str]:
        payload = {
            "model": self._local_model,
            "messages": messages,
            "temperature": temperature,
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

    def _local_chat_stream(
        self,
        messages: list[dict],
        temperature: float = 0.7,
        max_tokens: int = 4096,
    ) -> Iterator[str]:
        """Yield Ollama/OpenAI-compatible deltas without buffering a reply."""
        payload = {
            "model": self._local_model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": True,
        }
        endpoint = f"{self._local_url}/chat/completions"
        try:
            response = requests.post(
                endpoint,
                headers={"Content-Type": "application/json"},
                json=payload,
                timeout=(LOCAL_CONNECT_TIMEOUT, LOCAL_READ_TIMEOUT),
                stream=True,
            )
        except requests.exceptions.ConnectionError as exc:
            raise RuntimeError(f"{self._ollama_label()} — could not reach {endpoint}") from exc
        except Exception as exc:
            raise RuntimeError(f"{self._ollama_label()} — streaming request failed: {exc}") from exc

        try:
            if response.status_code != 200:
                raise RuntimeError(
                    f"{self._ollama_label()} — HTTP {response.status_code} from {endpoint}"
                )
            yield from iter_sse_content(response)
        finally:
            close = getattr(response, "close", None)
            if close:
                close()

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

    def _local_attempt(self, messages: list[dict], temperature: float, response_format: Optional[dict] = None) -> str:
        result = self._local_chat_completion(messages, temperature, response_format)
        if result:
            return result
        raise RuntimeError(
            f"{self._ollama_label()} — check that Ollama/LM Studio is running at {self._local_url}"
        )

    def _chain_order(self) -> list[str]:
        primary = self._provider
        if primary == "Local":
            return ["local", "omni", "remote"]
        if primary == "OmniRoute":
            return ["omni", "local", "remote"]
        return ["remote", "local", "omni"]

    def _run_chain(self, attempts: list[tuple[str, Callable[[], str]]]) -> str:
        """Try providers in order; auto-switch governs fallback; honest errors."""
        errors: list[str] = []
        tried = 0
        for index, (label, fn) in enumerate(attempts):
            if index > 0 and not self._auto_switch:
                break
            tried += 1
            try:
                result = fn()
                if result:
                    return result
                errors.append(f"{label} returned an empty response")
            except Exception as exc:
                errors.append(f"{label} failed ({exc})")
        if tried == 1 and not self._auto_switch:
            # Keep the original precise error for the primary provider.
            raise RuntimeError(errors[0]) if errors else RuntimeError("AI provider failed.")
        detail = "; ".join(errors) if errors else "No AI provider responded."
        raise RuntimeError(
            f"AI UNAVAILABLE — {detail}. "
            "Check config/api_keys.json and that Ollama/OmniRoute are running."
        )

    def _remote_chat(self, prompt: str, system: str, history, model, max_tokens, temperature) -> str:
        result = openrouter_client.chat(prompt, system, history, model, max_tokens, temperature)
        if result:
            return result
        raise RuntimeError("OpenRouter provider returned an empty response")

    # --- public API --------------------------------------------------------

    def chat(self, prompt: str, system: str = "You are a helpful assistant.", history: Optional[list[dict]] = None, model: Optional[str] = None, max_tokens: int = 4096, temperature: float = 0.7) -> str:
        self.reload_settings()
        messages = [{"role": "system", "content": system}]
        if history:
            messages.extend(history)
        messages.append({"role": "user", "content": prompt})

        def _local() -> str:
            return self._local_attempt(messages, temperature)

        def _omni() -> str:
            try:
                return self._omni.chat(prompt, system=system, history=history,
                                       model=model, max_tokens=max_tokens, temperature=temperature)
            except OmniRouteUnavailable as exc:
                raise RuntimeError(str(exc)) from exc

        def _remote() -> str:
            return self._remote_chat(prompt, system, history, model, max_tokens, temperature)

        by_name = {"local": ("OLLAMA/UNAVAILABLE", _local), "omni": ("OMNIROUTE", _omni), "remote": ("OpenRouter", _remote)}
        attempts: list[tuple[str, Callable[[], str]]] = []

        if self._provider == "OmniRoute" and not self._omni.is_configured():
            if not self._auto_switch:
                raise RuntimeError(
                    "OMNIROUTE UNAVAILABLE — OmniRoute is disabled or has no endpoint configured."
                )
            # OmniRoute unavailable -> fall back through local/remote
            order = ["local", "remote"]
        else:
            order = self._chain_order()

        for key in order:
            label, fn = by_name[key]
            if key == "omni" and not self._omni.is_configured():
                continue
            if key == "local":
                label = self._ollama_label()
            attempts.append((label, fn))

        return self._run_chain(attempts)

    def chat_stream(
        self,
        prompt: str,
        system: str = "You are a helpful assistant.",
        history: Optional[list[dict]] = None,
        model: Optional[str] = None,
        max_tokens: int = 4096,
        temperature: float = 0.5,
    ) -> Iterator[str]:
        """Stream text through the existing Local -> OmniRoute -> remote chain.

        A provider is only considered successful after its first non-empty
        delta.  If it fails before that point, the next configured provider is
        tried.  Once speech has begun, the error is raised instead of silently
        splicing two answers together.
        """
        self.reload_settings()
        messages = [{"role": "system", "content": system}]
        if history:
            messages.extend(history)
        messages.append({"role": "user", "content": prompt})

        def _local() -> Iterator[str]:
            return self._local_chat_stream(messages, temperature, max_tokens)

        def _omni() -> Iterator[str]:
            if not hasattr(self._omni, "chat_stream"):
                raise RuntimeError("OmniRoute streaming is not available")
            return self._omni.chat_stream(
                prompt, system=system, history=history, model=model,
                max_tokens=max_tokens, temperature=temperature,
            )

        def _remote() -> Iterator[str]:
            if not hasattr(openrouter_client, "chat_stream"):
                raise RuntimeError("OpenRouter streaming is not available")
            return openrouter_client.chat_stream(
                prompt, system=system, history=history, model=model,
                max_tokens=max_tokens, temperature=temperature,
            )

        by_name = {
            "local": (self._ollama_label(), _local),
            "omni": ("OMNIROUTE", _omni),
            "remote": ("OpenRouter", _remote),
        }
        if self._provider == "OmniRoute" and not self._omni.is_configured():
            order = ["local", "remote"] if self._auto_switch else []
        else:
            order = self._chain_order()

        errors: list[str] = []
        tried = 0
        for index, key in enumerate(order):
            if index > 0 and not self._auto_switch:
                break
            if key == "omni" and not self._omni.is_configured():
                continue
            tried += 1
            label, factory = by_name[key]
            received = False
            try:
                for delta in factory():
                    delta = str(delta or "")
                    if not delta:
                        continue
                    received = True
                    yield delta
                if received:
                    return
                errors.append(f"{label} returned an empty stream")
            except Exception as exc:
                errors.append(f"{label} failed ({exc})")
                if received:
                    raise

        detail = "; ".join(errors) if errors else "No AI provider responded."
        if tried == 1 and not self._auto_switch:
            raise RuntimeError(detail)
        raise RuntimeError(f"AI UNAVAILABLE — {detail}")

    def chat_json(self, prompt: str, system: str = "Return ONLY valid JSON.", model: Optional[str] = None, max_tokens: int = 4096) -> dict:
        self.reload_settings()
        messages = [
            {"role": "system", "content": system + " Output valid JSON only, without any markdown formatting."},
            {"role": "user", "content": prompt},
        ]

        def _local() -> dict:
            raw = self._local_attempt(messages, temperature=0.2, response_format={"type": "json_object"})
            return self._clean_json(raw)

        def _omni() -> dict:
            try:
                return self._omni.chat_json(prompt, system=system, model=model, max_tokens=max_tokens)
            except OmniRouteUnavailable as exc:
                raise RuntimeError(str(exc)) from exc

        def _remote() -> dict:
            result = openrouter_client.chat_json(prompt, system, model, max_tokens)
            if result:
                return result
            raise RuntimeError("OpenRouter provider returned an empty response")

        attempts: list[tuple[str, Callable[[], dict]]] = []
        if self._provider == "OmniRoute" and not self._omni.is_configured():
            order = ["local", "remote"] if self._auto_switch else []
        else:
            order = self._chain_order()
        for key in order:
            if key == "omni":
                if not self._omni.is_configured():
                    continue
                attempts.append(("OMNIROUTE", _omni))
            elif key == "local":
                attempts.append((self._ollama_label(), _local))
            else:
                attempts.append(("OpenRouter", _remote))
        # dict-returning variant of _run_chain
        errors: list[str] = []
        tried = 0
        for index, (label, fn) in enumerate(attempts):
            if index > 0 and not self._auto_switch:
                break
            tried += 1
            try:
                result = fn()
                if result:
                    return result
                errors.append(f"{label} returned an empty response")
            except Exception as exc:
                errors.append(f"{label} failed ({exc})")
        if tried == 1 and not self._auto_switch:
            raise RuntimeError(errors[0]) if errors else RuntimeError("AI provider failed.")
        detail = "; ".join(errors) if errors else "No AI provider responded."
        raise RuntimeError(
            f"AI UNAVAILABLE — {detail}. "
            "Check config/api_keys.json and that Ollama/OmniRoute are running."
        )

    def vision(self, prompt: str, image_b64: str, mime: str = "image/png", system: str = "Analyze the image.", model: Optional[str] = None, max_tokens: int = 1024) -> str:
        self.reload_settings()
        if self._provider == "OmniRoute":
            if not self._omni.is_configured():
                raise RuntimeError(
                    "OMNIROUTE UNAVAILABLE — OmniRoute is disabled or has no endpoint configured."
                )
            try:
                return self._omni.vision(prompt, image_b64, mime, system, model, max_tokens)
            except OmniRouteUnavailable as exc:
                raise RuntimeError(str(exc)) from exc
        if self._is_local_provider():
            messages = [
                {"role": "system", "content": system},
                {
                    "role": "user",
                    "content": [
                        {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{image_b64}"}},
                        {"type": "text", "text": prompt},
                    ],
                },
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
        elif self._provider == "OmniRoute":
            try:
                return self._omni.multi_turn(messages, model=model, max_tokens=max_tokens, temperature=temperature)
            except OmniRouteUnavailable as exc:
                raise RuntimeError(str(exc)) from exc
        else:
            return openrouter_client.multi_turn(messages, model, max_tokens, temperature)

    def route_status(self) -> dict:
        """Routing diagnostics (for About/System UI, logs and tests)."""
        self.reload_settings()
        return {
            "default_provider": self._provider,
            "local": {"url": self._local_url, "model": self._local_model},
            "omniroute": self._omni.status(),
            "auto_switch": self._auto_switch,
        }


client = UnifiedAIClient()
