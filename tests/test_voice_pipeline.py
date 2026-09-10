"""Behavioural tests for the measured low-latency voice primitives.

These tests are dependency-free: no microphone, Windows audio device, cloud
credential, browser, or AI backend is required. Runtime provider/audio checks
remain explicitly dependent on the Windows demonstration machine.
"""

import json

from streaming import InterruptibleAudioBuffer, SentenceChunker, iter_sse_content, stream_text_to_tts
from voice_pipeline import (
    VoiceActivityDetector,
    VoiceLatencyRecorder,
    VoiceLatencySummary,
    VoiceVADConfig,
)


class _SSE:
    def __init__(self, lines):
        self.lines = lines

    def iter_lines(self, decode_unicode=True):
        yield from self.lines


def test_speech_onset_requires_configured_confirmation():
    vad = VoiceActivityDetector(VoiceVADConfig(
        silence_timeout_ms=200, speech_onset_ms=100, minimum_speech_ms=100,
        base_rms_threshold=10, frame_ms=50,
    ))
    assert vad.process(100, timestamp=0.00) is None
    assert vad.process(100, timestamp=0.05) is None
    event = vad.process(100, timestamp=0.10)
    assert event and event.kind == "speech_start"
    assert event.speech_started_at == 0.0


def test_speech_termination_uses_hangover_not_first_silent_frame():
    vad = VoiceActivityDetector(VoiceVADConfig(
        silence_timeout_ms=200, speech_onset_ms=0, minimum_speech_ms=90,
        base_rms_threshold=10, frame_ms=50,
    ))
    assert vad.process(100, timestamp=0.00).kind == "speech_start"
    vad.process(100, timestamp=0.10)
    assert vad.process(0, timestamp=0.20) is None
    assert vad.process(0, timestamp=0.25) is None
    event = vad.process(0, timestamp=0.31)
    assert event and event.kind == "speech_end"
    assert event.silence_duration_ms >= 200
    assert event.speech_duration_ms >= 100


def test_noise_floor_does_not_treat_quiet_noise_as_speech():
    vad = VoiceActivityDetector(VoiceVADConfig(
        silence_timeout_ms=200, speech_onset_ms=0, minimum_speech_ms=50,
        base_rms_threshold=10, noise_multiplier=2.5,
    ))
    for index in range(20):
        assert vad.process(3, timestamp=index * 0.02) is None
    assert vad.in_speech is False
    assert vad.threshold() >= 10


def test_vad_parameters_are_environment_configurable(monkeypatch):
    monkeypatch.setenv("JARVIS_VOICE_SILENCE_MS", "180")
    monkeypatch.setenv("JARVIS_VOICE_ONSET_MS", "40")
    monkeypatch.setenv("JARVIS_VOICE_MIN_SPEECH_MS", "90")
    cfg = VoiceVADConfig.from_env()
    assert (cfg.silence_timeout_ms, cfg.speech_onset_ms, cfg.minimum_speech_ms) == (180, 40, 90)


def test_sse_parser_yields_deltas_without_waiting_for_complete_response():
    response = _SSE([
        'data: {"choices":[{"delta":{"content":"Hello"}}]}',
        'data: {"choices":[{"delta":{"content":" there."}}]}',
        "data: [DONE]",
    ])
    assert list(iter_sse_content(response)) == ["Hello", " there."]


def test_sentence_chunker_emits_first_sentence_early_and_flushes_tail():
    chunker = SentenceChunker(max_chars=100)
    assert chunker.feed("First useful sentence.") == ["First useful sentence."]
    assert chunker.feed(" Second sentence") == []
    assert chunker.flush() == ["Second sentence"]


def test_sentence_chunker_splits_long_stream_at_word_boundary():
    chunker = SentenceChunker(max_chars=40)
    chunks = chunker.feed("one two three four five six seven eight nine ten eleven")
    chunks += chunker.flush()
    assert len(chunks) >= 2
    assert "".join(chunks).replace(" ", "") == "onetwothreefourfivesixseveneightnineteneleven"


def test_stream_to_tts_is_serial_and_returns_exact_received_text():
    spoken = []
    received = stream_text_to_tts(
        ["The answer", " is ready. Next", " step is simple."],
        spoken.append,
    )
    assert received == "The answer is ready. Next step is simple."
    assert spoken == ["The answer is ready.", "Next step is simple."]


def test_interruptible_audio_buffer_discards_old_generation():
    buf = InterruptibleAudioBuffer()
    buf.put(b"old")
    generation = buf.interrupt()
    assert generation == 1
    assert buf.get() is None
    buf.put(b"new")
    assert buf.get() == b"new"


def test_latency_recorder_measures_t0_to_t6_stages(tmp_path):
    records = []
    recorder = VoiceLatencyRecorder(sink=records.append, log_path=tmp_path / "voice.jsonl")
    recorder.start_turn(10.000)
    recorder.mark_vad_end(280, 10.280)
    recorder.mark("transcript_available", 10.360)
    recorder.mark("intent_detected", 10.365)
    recorder.mark("llm_request_started", 10.280)
    recorder.mark("llm_first_token", 10.520)
    recorder.mark("tts_first_audio", 10.555)
    recorder.mark("playback_started", 10.570)
    result = recorder.complete(10.900)
    metrics = result["metrics_ms"]
    assert metrics["vad_delay_ms"] == 280
    assert round(metrics["stt_delay_ms"]) == 80
    assert round(metrics["intent_planner_delay_ms"]) == 5
    assert round(metrics["llm_first_token_from_t0_ms"]) == 240
    assert round(metrics["tts_first_audio_from_first_token_ms"]) == 35
    assert round(metrics["playback_startup_ms"]) == 15
    assert round(metrics["first_audible_output_ms"]) == 290
    assert round(metrics["total_response_time_ms"]) == 620
    assert records and (tmp_path / "voice.jsonl").exists()
    json.loads((tmp_path / "voice.jsonl").read_text().strip())


def test_latency_marks_each_stage_once_for_thread_safe_turn():
    recorder = VoiceLatencyRecorder(log_path="/tmp/jarvis-voice-test.jsonl")
    recorder.start_turn(1.0)
    recorder.mark("transcript_available", 1.2)
    recorder.mark("transcript_available", 1.8)
    result = recorder.complete(2.0)
    assert result["stages"]["transcript_available"] == 1.2


def test_native_audio_does_not_fabricate_a_text_token_timestamp():
    recorder = VoiceLatencyRecorder(log_path="/tmp/jarvis-voice-test.jsonl")
    recorder.start_turn(1.0)
    recorder.mark_vad_end(280, 1.3)
    recorder.mark("model_first_audio", 1.5)
    recorder.mark("tts_first_audio", 1.5)
    recorder.mark("playback_started", 1.52)
    metrics = recorder.complete(1.8)["metrics_ms"]
    assert metrics["llm_first_token_from_t0_ms"] is None
    assert round(metrics["model_first_audio_from_t0_ms"]) == 200


def test_latency_summary_reports_only_measured_values():
    records = [{"metrics_ms": {"first_audible_output_ms": 300, "total_response_time_ms": 700}},
               {"metrics_ms": {"first_audible_output_ms": 200, "total_response_time_ms": None}}]
    summary = VoiceLatencySummary.from_records(records)
    assert summary["first_audible_output_ms"]["count"] == 2
    assert summary["first_audible_output_ms"]["min_ms"] == 200
    assert summary["total_response_time_ms"]["count"] == 1


def test_no_audio_or_network_dependency_is_required_for_measurement_modules():
    # Importing these modules above and exercising their fake stream is the
    # intended offline check.  Real microphone/TTS status is reported by the
    # application only when the Windows runtime supplies those devices.
    assert VoiceActivityDetector is not None
    assert iter_sse_content is not None
