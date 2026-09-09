"""OmniRoute routing-layer tests (network-free, HTTP faked via monkeypatch).

Verifies that OmniRoute is a REAL, wired routing stage:
  - configuration state (enabled/endpoint/model) is read from settings;
  - the gateway client handles success, HTTP errors, connection errors,
    malformed JSON and JSON-mode responses and NEVER fakes a reply;
  - UnifiedAIClient inserts OmniRoute between Ollama and cloud in the chain
    and reports 'OMNIROUTE UNAVAILABLE' honestly when it cannot be reached.
"""

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import llm_client as llm
import omniroute as omni_mod
from omniroute import OmniRouteClient, OmniRouteUnavailable


def _write_settings(tmp_path: Path, **overrides) -> Path:
    data = {
        "default_ai_provider": "Local",
        "local_ai_url": "http://localhost:11434/v1",
        "local_ai_model": "llama3.2",
        "auto_provider_switch": True,
        "omniroute_enabled": True,
        "omniroute_url": "http://127.0.0.1:39000/v1",
        "omniroute_model": "",
    }
    data.update(overrides)
    path = tmp_path / "app_settings.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


def _make_post(handler):
    """Install a fake requests.post usable from both modules (they share requests)."""
    import requests
    return lambda url, headers=None, json=None, timeout=None: handler(url, json)


def _ok(content: str):
    class Resp:
        status_code = 200
        text = ""

        def json(self):
            return {"choices": [{"message": {"content": content}}]}

    return Resp()


# --------------------------------------------------------------------------
# OmniRouteClient unit behaviour
# --------------------------------------------------------------------------

def test_client_not_configured_when_disabled(tmp_path, monkeypatch):
    monkeypatch.setattr(omni_mod, "_get_base_dir", lambda: tmp_path)
    settings = tmp_path / "config" / "app_settings.json"
    settings.parent.mkdir(parents=True)
    settings.write_text(json.dumps({"omniroute_enabled": False,
                                    "omniroute_url": "http://x/v1"}), encoding="utf-8")
    client = OmniRouteClient()
    assert client.enabled is False
    assert client.is_configured() is False
    assert client.health() is False
    with pytest.raises(OmniRouteUnavailable) as exc:
        client.chat("hi")
    assert "OMNIROUTE UNAVAILABLE" in str(exc.value)


def test_client_chat_success(tmp_path, monkeypatch):
    monkeypatch.setattr(omni_mod, "_get_base_dir", lambda: tmp_path)
    settings = tmp_path / "config" / "app_settings.json"
    settings.parent.mkdir(parents=True)
    settings.write_text(json.dumps({"omniroute_enabled": True,
                                    "omniroute_url": "http://127.0.0.1:39000/v1"}),
                        encoding="utf-8")
    seen = {}

    def handler(url, payload):
        seen["url"] = url
        seen["payload"] = payload
        return _ok(" answer from omni ")

    monkeypatch.setattr(omni_mod.requests, "post", _make_post(handler))
    client = OmniRouteClient()
    assert client.is_configured() is True
    assert client.chat("hi", system="You are J.A.R.V.I.S.") == "answer from omni"
    assert seen["url"].endswith("/chat/completions")
    assert seen["payload"]["messages"][0]["content"] == "You are J.A.R.V.I.S."
    assert seen["payload"]["messages"][-1]["content"] == "hi"


def test_client_http_error_is_honest(tmp_path, monkeypatch):
    monkeypatch.setattr(omni_mod, "_get_base_dir", lambda: tmp_path)
    settings = tmp_path / "config" / "app_settings.json"
    settings.parent.mkdir(parents=True)
    settings.write_text(json.dumps({"omniroute_enabled": True,
                                    "omniroute_url": "http://127.0.0.1:39000/v1"}),
                        encoding="utf-8")

    class Resp:
        status_code = 502
        text = "bad gateway"

    monkeypatch.setattr(omni_mod.requests, "post",
                        lambda *a, **k: Resp())
    client = OmniRouteClient()
    with pytest.raises(OmniRouteUnavailable) as exc:
        client.chat("hi")
    assert "OMNIROUTE UNAVAILABLE" in str(exc.value)
    assert "502" in str(exc.value)


def test_client_connection_error_reports_endpoint(tmp_path, monkeypatch):
    import requests
    monkeypatch.setattr(omni_mod, "_get_base_dir", lambda: tmp_path)
    settings = tmp_path / "config" / "app_settings.json"
    settings.parent.mkdir(parents=True)
    settings.write_text(json.dumps({"omniroute_enabled": True,
                                    "omniroute_url": "http://127.0.0.1:39000/v1"}),
                        encoding="utf-8")

    def boom(url, headers=None, json=None, timeout=None):
        raise requests.exceptions.ConnectionError("refused")

    monkeypatch.setattr(omni_mod.requests, "post", boom)
    client = OmniRouteClient()
    with pytest.raises(OmniRouteUnavailable) as exc:
        client.chat("hi")
    message = str(exc.value)
    assert "OMNIROUTE UNAVAILABLE" in message
    assert "39000" in message


def test_client_chat_json_fence(tmp_path, monkeypatch):
    monkeypatch.setattr(omni_mod, "_get_base_dir", lambda: tmp_path)
    settings = tmp_path / "config" / "app_settings.json"
    settings.parent.mkdir(parents=True)
    settings.write_text(json.dumps({"omniroute_enabled": True,
                                    "omniroute_url": "http://127.0.0.1:39000/v1"}),
                        encoding="utf-8")

    def handler(url, payload):
        return _ok('```json\n{"router": "omni"}\n```')

    monkeypatch.setattr(omni_mod.requests, "post", _make_post(handler))
    client = OmniRouteClient()
    assert client.chat_json("make json") == {"router": "omni"}


# --------------------------------------------------------------------------
# UnifiedAIClient integration (OmniRoute sits in the middle of the chain)
# --------------------------------------------------------------------------

def _install(monkeypatch, tmp_path, remote, **settings):
    # llm_client reads SETTINGS_PATH directly; OmniRouteClient reads from
    # <base_dir>/config/app_settings.json — use the same file for both.
    cfg_dir = tmp_path / "config"
    cfg_dir.mkdir(exist_ok=True)
    settings_path = cfg_dir / "app_settings.json"
    data = {
        "default_ai_provider": "Local",
        "local_ai_url": "http://localhost:11434/v1",
        "local_ai_model": "llama3.2",
        "auto_provider_switch": True,
        "omniroute_enabled": True,
        "omniroute_url": "http://127.0.0.1:39000/v1",
        "omniroute_model": "",
    }
    data.update(settings)
    settings_path.write_text(json.dumps(data), encoding="utf-8")
    monkeypatch.setattr(llm, "SETTINGS_PATH", settings_path)
    monkeypatch.setattr(omni_mod, "_get_base_dir", lambda: tmp_path)
    monkeypatch.setattr(llm, "openrouter_client", remote)
    return llm.UnifiedAIClient()


def test_chain_local_first_then_omni_then_remote(tmp_path, monkeypatch):
    """With Local default: local down -> OmniRoute down -> OpenRouter succeeds."""
    import requests
    calls = []

    def handler(url, headers=None, json=None, timeout=None):
        calls.append(url)
        if "11434" in url:
            raise requests.exceptions.ConnectionError("local refused")
        if "39000" in url:
            raise requests.exceptions.ConnectionError("omni refused")
        return _ok("remote rescue")

    monkeypatch.setattr(llm.requests, "post", handler)
    remote = llm_mod_fake_remote()
    client = _install(monkeypatch, tmp_path, remote, default_ai_provider="Local",
                      omniroute_enabled=True, omniroute_url="http://127.0.0.1:39000/v1")
    assert client.chat("hi") == "remote reply"
    # order: local(Ollama) endpoint first, OmniRoute second
    assert any("11434" in u for u in calls)
    assert any("39000" in u for u in calls)
    assert calls.index(next(u for u in calls if "39000" in u)) > calls.index(next(u for u in calls if "11434" in u))


def test_omniroute_as_default_primary(tmp_path, monkeypatch):
    calls = []

    def handler(url, headers=None, json=None, timeout=None):
        calls.append(url)
        if "39000" in url:
            return _ok("omni primary answer")
        return _ok("should not reach")

    monkeypatch.setattr(llm.requests, "post", handler)
    client = _install(monkeypatch, tmp_path, llm_mod_fake_remote(),
                      default_ai_provider="OmniRoute",
                      omniroute_enabled=True, omniroute_url="http://127.0.0.1:39000/v1")
    assert client.chat("hi") == "omni primary answer"
    assert calls and "39000" in calls[0]


def test_omniroute_disabled_as_default_without_auto_raises(tmp_path, monkeypatch):
    client = _install(monkeypatch, tmp_path, llm_mod_fake_remote(),
                      default_ai_provider="OmniRoute",
                      omniroute_enabled=False,
                      omniroute_url="http://127.0.0.1:39000/v1",
                      auto_provider_switch=False)
    with pytest.raises(RuntimeError) as exc:
        client.chat("hi")
    assert "OMNIROUTE UNAVAILABLE" in str(exc.value)


def test_all_providers_down_reports_omniroute(tmp_path, monkeypatch):
    import requests

    def handler(url, payload):
        raise requests.exceptions.ConnectionError("refused")

    monkeypatch.setattr(llm.requests, "post", handler)
    remote = llm_mod_fake_remote(chat_error=RuntimeError("no OpenRouter key"))
    client = _install(monkeypatch, tmp_path, remote,
                      default_ai_provider="Local",
                      omniroute_enabled=True, omniroute_url="http://127.0.0.1:39000/v1")
    with pytest.raises(RuntimeError) as exc:
        client.chat("hi")
    message = str(exc.value)
    assert "AI UNAVAILABLE" in message
    assert "OMNIROUTE" in message
    assert "OLLAMA UNAVAILABLE" in message


def test_route_status_reports_omniroute(tmp_path, monkeypatch):
    client = _install(monkeypatch, tmp_path, llm_mod_fake_remote(),
                      default_ai_provider="OpenRouter",
                      omniroute_enabled=True, omniroute_url="http://127.0.0.1:39000/v1")
    status = client.route_status()
    assert status["omniroute"]["enabled"] is True
    assert status["omniroute"]["endpoint"] == "http://127.0.0.1:39000/v1"
    assert status["default_provider"] == "OpenRouter"


def llm_mod_fake_remote(chat_result="remote reply", chat_error=None):
    class FakeRemote:
        def chat(self, prompt, system="", history=None, model=None, max_tokens=4096, temperature=0.7):
            if chat_error:
                raise chat_error
            return chat_result

        def chat_json(self, prompt, system="", model=None, max_tokens=4096):
            return {"ok": True}

        def vision(self, prompt, image_b64, mime="image/png", system="", model=None, max_tokens=1024):
            return "vision"

    return FakeRemote()
