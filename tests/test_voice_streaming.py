"""Provider-boundary tests for voice streaming and honest failures."""

import json
from pathlib import Path

import pytest

from streaming import SentenceChunker, stream_text_to_tts


class FakeResponse:
    status_code = 200
    text = ""

    def __init__(self, lines):
        self._lines = lines
        self.closed = False

    def iter_lines(self, decode_unicode=True):
        yield from self._lines

    def close(self):
        self.closed = True


def test_streaming_tts_failure_is_not_silent():
    def unavailable(_chunk):
        raise RuntimeError("TTS unavailable")

    with pytest.raises(RuntimeError, match="TTS unavailable"):
        stream_text_to_tts(["Short answer."], unavailable, chunker=SentenceChunker())


def test_short_response_is_played_without_waiting_for_a_second_sentence():
    spoken = []
    text = stream_text_to_tts(["Short answer."], spoken.append)
    assert text == "Short answer."
    assert spoken == ["Short answer."]


def test_long_response_is_chunked_without_overlap():
    spoken = []
    text = stream_text_to_tts(
        ["First sentence. Second sentence. Third sentence."],
        spoken.append,
    )
    assert text == "First sentence. Second sentence. Third sentence."
    assert spoken == ["First sentence.", "Second sentence.", "Third sentence."]


def test_local_ollama_streams_deltas(monkeypatch, tmp_path):
    requests = pytest.importorskip("requests")
    import llm_client as module

    settings = tmp_path / "app_settings.json"
    settings.write_text(json.dumps({
        "default_ai_provider": "Local",
        "local_ai_url": "http://localhost:11434/v1",
        "local_ai_model": "llama3.2",
        "auto_provider_switch": False,
    }), encoding="utf-8")
    monkeypatch.setattr(module, "SETTINGS_PATH", Path(settings))
    seen = {}

    def post(url, headers=None, json=None, timeout=None, stream=False):
        seen.update(url=url, payload=json, stream=stream)
        return FakeResponse([
            'data: {"choices":[{"delta":{"content":"first"}}]}',
            'data: {"choices":[{"delta":{"content":" second."}}]}',
            "data: [DONE]",
        ])

    monkeypatch.setattr(module.requests, "post", post)
    client = module.UnifiedAIClient()
    assert "".join(client.chat_stream("hello")) == "first second."
    assert seen["stream"] is True
    assert seen["payload"]["stream"] is True


def test_streaming_provider_error_falls_back_before_audio(monkeypatch, tmp_path):
    pytest.importorskip("requests")
    import llm_client as module

    settings = tmp_path / "app_settings.json"
    settings.write_text(json.dumps({
        "default_ai_provider": "Local",
        "local_ai_url": "http://localhost:11434/v1",
        "local_ai_model": "llama3.2",
        "auto_provider_switch": True,
    }), encoding="utf-8")
    monkeypatch.setattr(module, "SETTINGS_PATH", settings)

    def post(*args, **kwargs):
        raise module.requests.exceptions.ConnectionError("Ollama down")

    monkeypatch.setattr(module.requests, "post", post)

    class Remote:
        def chat_stream(self, *args, **kwargs):
            yield "remote"
            yield " answer."

    monkeypatch.setattr(module, "openrouter_client", Remote())
    client = module.UnifiedAIClient()
    assert "".join(client.chat_stream("hello")) == "remote answer."


def test_streaming_all_backends_unavailable_is_honest(monkeypatch, tmp_path):
    pytest.importorskip("requests")
    import llm_client as module

    settings = tmp_path / "app_settings.json"
    settings.write_text(json.dumps({
        "default_ai_provider": "Local",
        "local_ai_url": "http://localhost:11434/v1",
        "auto_provider_switch": False,
    }), encoding="utf-8")
    monkeypatch.setattr(module, "SETTINGS_PATH", settings)
    monkeypatch.setattr(module.requests, "post", lambda *a, **k: (_ for _ in ()).throw(
        module.requests.exceptions.ConnectionError("down")))
    with pytest.raises(RuntimeError, match="OLLAMA UNAVAILABLE|AI UNAVAILABLE"):
        list(module.UnifiedAIClient().chat_stream("hello"))
