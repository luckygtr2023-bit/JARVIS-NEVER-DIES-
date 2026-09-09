"""Targeted tests for the J.A.R.V.I.S. AI-provider routing layer.

These tests exercise llm_client.UnifiedAIClient provider selection, local
(Ollama-compatible) routing, and the auto-provider-switch fallback with
honest error propagation. No network access is used — requests and the remote
client are faked via monkeypatch.
"""

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import llm_client as llm
from llm_client import UnifiedAIClient, normalize_provider


def _write_settings(tmp_path: Path, **overrides) -> str:
    data = {
        "default_ai_provider": "Local",
        "local_ai_url": "http://localhost:11434/v1",
        "local_ai_model": "llama3.2",
        "auto_provider_switch": True,
    }
    data.update(overrides)
    path = tmp_path / "app_settings.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    return str(path)


class FakeRemote:
    """Stands in for or_client.OpenRouterClient."""

    def __init__(self, chat_result="remote reply", chat_json_result=None,
                 chat_error=None, chat_json_error=None):
        self._chat_result = chat_result
        self._chat_json_result = chat_json_result
        self._chat_error = chat_error
        self._chat_json_error = chat_json_error
        self.calls = []

    def chat(self, prompt, system="", history=None, model=None, max_tokens=4096, temperature=0.7):
        self.calls.append(("chat", prompt))
        if self._chat_error:
            raise self._chat_error
        return self._chat_result

    def chat_json(self, prompt, system="", model=None, max_tokens=4096):
        self.calls.append(("chat_json", prompt))
        if self._chat_json_error:
            raise self._chat_json_error
        if self._chat_json_result is None:
            raise RuntimeError("remote chat_json not stubbed")
        return self._chat_json_result


def _install_fakes(monkeypatch, tmp_path, remote=None, **settings):
    monkeypatch.setattr(llm, "SETTINGS_PATH", Path(_write_settings(tmp_path, **settings)))
    remote = remote or FakeRemote()
    monkeypatch.setattr(llm, "openrouter_client", remote)
    return UnifiedAIClient()


def test_normalize_provider_aliases():
    assert normalize_provider("Google Gemini") == "Gemini"
    assert normalize_provider("gemini") == "Gemini"
    assert normalize_provider("ollama") == "Local"
    assert normalize_provider("Local") == "Local"
    assert normalize_provider("OpenRouter") == "OpenRouter"
    assert normalize_provider(None) == "OpenRouter"


def test_local_provider_success(monkeypatch, tmp_path):
    captured = {}

    def fake_post(url, headers=None, json=None, timeout=None):
        captured["url"] = url
        captured["payload"] = json
        captured["timeout"] = timeout

        class Resp:
            status_code = 200
            text = ""

            def json(self):
                return {"choices": [{"message": {"content": " hello from ollama "}}]}

        return Resp()

    monkeypatch.setattr(llm.requests, "post", fake_post)
    client = _install_fakes(monkeypatch, tmp_path, default_ai_provider="Local")
    result = client.chat("Say hi", system="You are J.A.R.V.I.S.")
    assert result == "hello from ollama"
    assert captured["url"].endswith("/chat/completions")
    assert captured["payload"]["model"] == "llama3.2"
    assert captured["payload"]["messages"][0]["content"] == "You are J.A.R.V.I.S."
    assert captured["timeout"][0] > 0  # connect timeout configured


def test_local_down_auto_switch_to_remote(monkeypatch, tmp_path):
    import requests

    def fake_post(url, headers=None, json=None, timeout=None):
        raise requests.exceptions.ConnectionError("connection refused")

    monkeypatch.setattr(llm.requests, "post", fake_post)
    remote = FakeRemote(chat_result="remote fallback answer")
    client = _install_fakes(monkeypatch, tmp_path, remote=remote, default_ai_provider="Local")
    assert client.chat("hi") == "remote fallback answer"
    assert ("chat", "hi") in remote.calls


def test_local_down_auto_switch_disabled_raises(monkeypatch, tmp_path):
    import requests

    def fake_post(url, headers=None, json=None, timeout=None):
        raise requests.exceptions.ConnectionError("connection refused")

    monkeypatch.setattr(llm.requests, "post", fake_post)
    client = _install_fakes(monkeypatch, tmp_path, default_ai_provider="Local", auto_provider_switch=False)
    with pytest.raises(RuntimeError) as exc:
        client.chat("hi")
    assert "OLLAMA UNAVAILABLE" in str(exc.value)


def test_both_providers_fail_raises_honest_error(monkeypatch, tmp_path):
    import requests

    def fake_post(url, headers=None, json=None, timeout=None):
        raise requests.exceptions.ConnectionError("connection refused")

    monkeypatch.setattr(llm.requests, "post", fake_post)
    remote = FakeRemote(chat_error=RuntimeError("no OpenRouter key"))
    client = _install_fakes(monkeypatch, tmp_path, remote=remote, default_ai_provider="Local")
    with pytest.raises(RuntimeError) as exc:
        client.chat("hi")
    message = str(exc.value)
    assert "AI UNAVAILABLE" in message
    assert "OLLAMA UNAVAILABLE" in message


def test_remote_primary_down_switches_to_local(monkeypatch, tmp_path):
    captured = {}

    def fake_post(url, headers=None, json=None, timeout=None):
        captured["called"] = True

        class Resp:
            status_code = 200
            text = ""

            def json(self):
                return {"choices": [{"message": {"content": "local rescue answer"}}]}

        return Resp()

    monkeypatch.setattr(llm.requests, "post", fake_post)
    remote = FakeRemote(chat_error=RuntimeError("rate limited"))
    client = _install_fakes(monkeypatch, tmp_path, remote=remote, default_ai_provider="OpenRouter")
    assert client.chat("hi") == "local rescue answer"
    assert captured.get("called") is True


def test_chat_json_local_markdown_fence(monkeypatch, tmp_path):
    def fake_post(url, headers=None, json=None, timeout=None):
        class Resp:
            status_code = 200
            text = ""

            def json(self):
                content = '```json\n{"owner": "Lucky"}\n```'
                return {"choices": [{"message": {"content": content}}]}

        return Resp()

    monkeypatch.setattr(llm.requests, "post", fake_post)
    client = _install_fakes(monkeypatch, tmp_path, default_ai_provider="Local")
    assert client.chat_json("make json") == {"owner": "Lucky"}


def test_chat_json_local_fails_remote_dict(monkeypatch, tmp_path):
    def fake_post(url, headers=None, json=None, timeout=None):
        class Resp:
            status_code = 500
            text = "boom"

            def json(self):
                return {}

        return Resp()

    monkeypatch.setattr(llm.requests, "post", fake_post)
    remote = FakeRemote(chat_json_result={"ok": True})
    client = _install_fakes(monkeypatch, tmp_path, remote=remote, default_ai_provider="Local")
    assert client.chat_json("make json") == {"ok": True}


def test_default_provider_without_settings_file(monkeypatch, tmp_path):
    """No app_settings.json -> fall back to remote routing, never a fake answer."""
    missing = tmp_path / "does-not-exist.json"
    monkeypatch.setattr(llm, "SETTINGS_PATH", missing)
    remote = FakeRemote(chat_result="remote reply")
    monkeypatch.setattr(llm, "openrouter_client", remote)
    client = UnifiedAIClient()
    assert client._provider == "OpenRouter"
    assert client.chat("hi") == "remote reply"
