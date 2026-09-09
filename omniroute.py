"""OmniRoute — optional OpenAI-compatible AI routing layer for J.A.R.V.I.S.

OmniRoute is a *configurable local/remote gateway* that receives normalized
OpenAI-style chat requests and forwards them to a configured downstream
provider (OpenRouter, Gemini, or any other OpenAI-compatible service the
gateway is configured for). This module is a real client for that gateway —
it is NOT a fake endpoint and it does NOT invent responses.

Architecture position:

    J.A.R.V.I.S. router
        -> LOCAL OLLAMA        (offline-first)
        -> OMNIROUTE           (optional configured gateway)
        -> OPENROUTER/GEMINI   (cloud)

Configuration (config/app_settings.json):
    omniroute_enabled : bool   (default False)
    omniroute_url     : str    (default http://127.0.0.1:39000/v1)
    omniroute_model   : str    (optional override model name)

Optional credential (config/api_keys.json):
    omniroute_api_key : str    (never logged, never required for local gateways)

Error contract: when the gateway cannot be reached or returns a non-success
HTTP status, an OmniRouteUnavailable exception is raised whose message starts
with "OMNIROUTE UNAVAILABLE" and includes the endpoint. The client never
returns a fabricated successful answer.
"""

from __future__ import annotations

import json
import logging
import sys
from pathlib import Path
from typing import Any, Optional

import requests

logger = logging.getLogger("omniroute")

DEFAULT_OMNIROUTE_URL = "http://127.0.0.1:39000/v1"
CONNECT_TIMEOUT = 8.0
READ_TIMEOUT = 150.0


def _get_base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent


class OmniRouteUnavailable(RuntimeError):
    """Raised when the OmniRoute gateway is unreachable / errored."""


def _truncate(text: str, limit: int = 300) -> str:
    text = (text or "").strip()
    return text[:limit] + ("…" if len(text) > limit else "")


class OmniRouteClient:
    """OpenAI-compatible client for a configurable OmniRoute gateway."""

    def __init__(self) -> None:
        self._enabled = False
        self._url = DEFAULT_OMNIROUTE_URL
        self._model = ""
        self._api_key = ""
        self.reload()

    def reload(self) -> None:
        base = _get_base_dir()
        settings_path = base / "config" / "app_settings.json"
        keys_path = base / "config" / "api_keys.json"
        try:
            if settings_path.exists():
                data = json.loads(settings_path.read_text(encoding="utf-8"))
                self._enabled = bool(data.get("omniroute_enabled", False))
                self._url = str(data.get("omniroute_url") or DEFAULT_OMNIROUTE_URL).rstrip("/")
                self._model = str(data.get("omniroute_model") or "").strip()
        except Exception as exc:
            logger.error(f"[OmniRoute] settings load failed: {exc}")
        try:
            if keys_path.exists():
                keys = json.loads(keys_path.read_text(encoding="utf-8"))
                self._api_key = str(keys.get("omniroute_api_key") or "").strip()
        except Exception:
            self._api_key = ""

    # --- state --------------------------------------------------------------

    @property
    def enabled(self) -> bool:
        return self._enabled

    @property
    def endpoint(self) -> str:
        return self._url

    @property
    def model(self) -> str:
        return self._model

    def is_configured(self) -> bool:
        """True when the router is both enabled and has a usable endpoint."""
        return self._enabled and bool(self._url)

    def status(self) -> dict[str, Any]:
        """Human/UI-facing routing state (never raises)."""
        return {
            "enabled": self._enabled,
            "configured": self.is_configured(),
            "endpoint": self._url,
            "model": self._model or None,
            "reachable": self.health() if self.is_configured() else False,
        }

    def health(self) -> bool:
        """Probe the gateway (used for diagnostics / tests)."""
        if not self.is_configured():
            return False
        try:
            resp = requests.get(f"{self._url}/models", timeout=(CONNECT_TIMEOUT, 10.0))
            return resp.status_code == 200
        except Exception:
            return False

    # --- internals ----------------------------------------------------------

    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"
        return headers

    def _request(self, payload: dict) -> str:
        endpoint = f"{self._url}/chat/completions"
        if not self.is_configured():
            raise OmniRouteUnavailable(
                "OMNIROUTE UNAVAILABLE — OmniRoute is disabled or has no endpoint configured. "
                "Enable it in Settings > AI Providers and set an endpoint."
            )
        try:
            resp = requests.post(
                endpoint,
                headers=self._headers(),
                json=payload,
                timeout=(CONNECT_TIMEOUT, READ_TIMEOUT),
            )
        except requests.exceptions.ConnectionError as exc:
            raise OmniRouteUnavailable(
                f"OMNIROUTE UNAVAILABLE — cannot reach {endpoint} ({exc}). "
                "Start the OmniRoute gateway or disable OmniRoute in Settings."
            ) from exc
        except Exception as exc:
            raise OmniRouteUnavailable(
                f"OMNIROUTE UNAVAILABLE — request to {endpoint} failed ({exc})."
            ) from exc

        if resp.status_code != 200:
            raise OmniRouteUnavailable(
                f"OMNIROUTE UNAVAILABLE — HTTP {resp.status_code} from {endpoint}: {_truncate(resp.text)}"
            )
        try:
            data = resp.json()
        except Exception as exc:
            raise OmniRouteUnavailable(
                f"OMNIROUTE UNAVAILABLE — malformed JSON from {endpoint} ({exc})."
            ) from exc
        content = ""
        try:
            content = data["choices"][0]["message"]["content"] or ""
        except Exception:
            raise OmniRouteUnavailable(
                f"OMNIROUTE UNAVAILABLE — response from {endpoint} had no usable content."
            )
        content = content.strip()
        if not content:
            raise OmniRouteUnavailable(
                f"OMNIROUTE UNAVAILABLE — empty content from {endpoint}."
            )
        return content

    def _payload(self, messages: list[dict], *, temperature: float, max_tokens: int,
                 response_format: Optional[dict], model: Optional[str]) -> dict:
        payload: dict[str, Any] = {
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if response_format:
            payload["response_format"] = response_format
        selected = (self._model or model or "").strip()
        if selected:
            payload["model"] = selected
        return payload

    # --- public API (OpenAI-compatible) -------------------------------------

    def chat(self, prompt: str, system: str = "You are a helpful assistant.",
             history: Optional[list[dict]] = None, model: Optional[str] = None,
             max_tokens: int = 4096, temperature: float = 0.7) -> str:
        messages = [{"role": "system", "content": system}]
        if history:
            messages.extend(history)
        messages.append({"role": "user", "content": prompt})
        return self._request(self._payload(messages, temperature=temperature,
                                           max_tokens=max_tokens,
                                           response_format=None, model=model))

    def multi_turn(self, messages: list[dict], model: Optional[str] = None,
                   max_tokens: int = 4096, temperature: float = 0.7) -> str:
        return self._request(self._payload(messages, temperature=temperature,
                                           max_tokens=max_tokens,
                                           response_format=None, model=model))

    def chat_json(self, prompt: str, system: str = "Return ONLY valid JSON.",
                  model: Optional[str] = None, max_tokens: int = 4096) -> dict:
        messages = [
            {"role": "system", "content": system + " Output valid JSON only, without any markdown formatting."},
            {"role": "user", "content": prompt},
        ]
        raw = self._request(self._payload(messages, temperature=0.2,
                                          max_tokens=max_tokens,
                                          response_format={"type": "json_object"},
                                          model=model))
        clean = raw.strip()
        if clean.startswith("```"):
            parts = clean.split("```")
            clean = parts[1] if len(parts) > 1 else clean
            if clean.startswith("json"):
                clean = clean[4:]
        clean = clean.strip().rstrip("`").strip()
        try:
            return json.loads(clean)
        except json.JSONDecodeError as exc:
            raise OmniRouteUnavailable(
                f"OMNIROUTE UNAVAILABLE — unparseable JSON from gateway: {exc}"
            ) from exc

    def vision(self, prompt: str, image_b64: str, mime: str = "image/png",
               system: str = "Analyze the image.", model: Optional[str] = None,
               max_tokens: int = 1024) -> str:
        """Forward a multimodal (image) request through the OmniRoute gateway."""
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
        return self._request(self._payload(messages, temperature=0.2,
                                           max_tokens=max_tokens,
                                           response_format=None, model=model))


# module-level client bound to the same config files as the rest of J.A.R.V.I.S.
client = OmniRouteClient()
