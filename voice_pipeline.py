"""Voice timing, VAD, and streaming policy primitives for J.A.R.V.I.S.

The Windows voice path is Gemini Live first: microphone PCM is already sent
continuously and Gemini returns streaming native audio.  This module adds
local, measurable VAD timing around that path and a streaming text/TTS path
for the disconnected fallback.  It intentionally has no audio or network
dependency, which keeps startup and tests safe on machines without devices.
"""

from __future__ import annotations

import json
import os
import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional


@dataclass(frozen=True)
class VoiceVADConfig:
    """Configurable local VAD policy; values are milliseconds unless noted."""

    silence_timeout_ms: int = 320
    speech_onset_ms: int = 64
    minimum_speech_ms: int = 128
    base_rms_threshold: float = 10.0
    echo_rms_threshold: float = 1200.0
    noise_multiplier: float = 2.5
    noise_floor_alpha: float = 0.08
    frame_ms: int = 32

    @classmethod
    def from_env(cls) -> "VoiceVADConfig":
        def integer(name: str, default: int, minimum: int) -> int:
            try:
                return max(minimum, int(os.getenv(name, default)))
            except (TypeError, ValueError):
                return default

        def number(name: str, default: float, minimum: float) -> float:
            try:
                return max(minimum, float(os.getenv(name, default)))
            except (TypeError, ValueError):
                return default

        return cls(
            silence_timeout_ms=integer("JARVIS_VOICE_SILENCE_MS", 320, 80),
            speech_onset_ms=integer("JARVIS_VOICE_ONSET_MS", 64, 0),
            minimum_speech_ms=integer("JARVIS_VOICE_MIN_SPEECH_MS", 128, 0),
            base_rms_threshold=number("JARVIS_VOICE_RMS_THRESHOLD", 10.0, 0.0),
            echo_rms_threshold=number("JARVIS_VOICE_ECHO_RMS_THRESHOLD", 1200.0, 0.0),
            noise_multiplier=number("JARVIS_VOICE_NOISE_MULTIPLIER", 2.5, 1.0),
            noise_floor_alpha=min(1.0, number("JARVIS_VOICE_NOISE_ALPHA", 0.08, 0.001)),
            frame_ms=integer("JARVIS_VOICE_FRAME_MS", 32, 1),
        )


@dataclass(frozen=True)
class VADEvent:
    kind: str
    timestamp: float
    speech_started_at: float | None = None
    last_voice_at: float | None = None
    speech_duration_ms: float = 0.0
    silence_duration_ms: float = 0.0
    threshold: float = 0.0


class VoiceActivityDetector:
    """Small RMS VAD with onset confirmation and configurable hangover.

    It does not discard the microphone stream.  The caller can continue
    sending PCM/silence to the Live session while this class only reports
    timing events.  That preserves Gemini's own streaming transcription and
    server-side activity detection.
    """

    def __init__(self, config: VoiceVADConfig | None = None) -> None:
        self.config = config or VoiceVADConfig.from_env()
        self.reset()

    def reset(self) -> None:
        self.in_speech = False
        self._candidate_started: float | None = None
        self._speech_started: float | None = None
        self._last_voice: float | None = None
        self._noise_floor = 0.0

    @property
    def noise_floor(self) -> float:
        return self._noise_floor

    def threshold(self, override: float | None = None) -> float:
        learned = self._noise_floor * self.config.noise_multiplier
        return max(self.config.base_rms_threshold, learned, override or 0.0)

    def process(
        self,
        rms: float,
        *,
        timestamp: float | None = None,
        threshold_override: float | None = None,
    ) -> VADEvent | None:
        now = time.monotonic() if timestamp is None else float(timestamp)
        value = max(0.0, float(rms))
        limit = self.threshold(threshold_override)
        voiced = value >= limit

        if not self.in_speech:
            if not voiced:
                alpha = self.config.noise_floor_alpha
                self._noise_floor = (1.0 - alpha) * self._noise_floor + alpha * value
                return None
            if self._candidate_started is None:
                self._candidate_started = now
            if (now - self._candidate_started) * 1000.0 < self.config.speech_onset_ms:
                return None
            self.in_speech = True
            self._last_voice = now
            started = self._candidate_started
            self._speech_started = started
            self._candidate_started = None
            return VADEvent(
                kind="speech_start",
                timestamp=now,
                speech_started_at=started,
                last_voice_at=now,
                threshold=limit,
            )

        if voiced:
            self._last_voice = now
            return None

        # Hangover prevents a short pause between words from terminating a
        # normal utterance.  The end timestamp is the first frame after the
        # configured silence, quantized by the audio callback period.
        last_voice = self._last_voice if self._last_voice is not None else now
        silent_ms = (now - last_voice) * 1000.0
        if silent_ms < self.config.silence_timeout_ms:
            return None

        started = self._speech_started if self._speech_started is not None else last_voice
        duration_ms = max(0.0, (last_voice - started) * 1000.0)
        self.reset()
        if duration_ms < self.config.minimum_speech_ms:
            # Ignore noise bursts without losing the next utterance.
            return None
        return VADEvent(
            kind="speech_end",
            timestamp=now,
            speech_started_at=started,
            last_voice_at=last_voice,
            speech_duration_ms=duration_ms,
            silence_duration_ms=silent_ms,
            threshold=limit,
        )


_STAGE_NAMES = (
    "speech_started",
    "vad_end",
    "transcript_available",
    "intent_detected",
    "llm_request_started",
    "llm_first_token",
    "model_first_audio",
    "tts_first_audio",
    "playback_started",
    "completed",
)


@dataclass
class VoiceTurnMetrics:
    turn_id: str
    source: str = "gemini-live"
    timestamps: dict[str, float] = field(default_factory=dict)
    vad_silence_delay_ms: float | None = None
    notes: list[str] = field(default_factory=list)

    def mark(self, stage: str, timestamp: float | None = None) -> float:
        if stage not in _STAGE_NAMES:
            raise ValueError(f"unknown voice stage: {stage}")
        value = time.monotonic() if timestamp is None else float(timestamp)
        self.timestamps.setdefault(stage, value)
        return value

    def _delta_ms(self, first: str, second: str, *, allow_negative: bool = False) -> float | None:
        a = self.timestamps.get(first)
        b = self.timestamps.get(second)
        if a is None or b is None:
            return None
        value = (b - a) * 1000.0
        return value if allow_negative else max(0.0, value)

    def as_dict(self) -> dict:
        t0 = self.timestamps.get("vad_end")
        metrics = {
            # VAD termination is measured from the last voiced frame, not
            # guessed from a typical microphone or model latency.
            "vad_delay_ms": self.vad_silence_delay_ms,
            "stt_delay_ms": self._delta_ms("vad_end", "transcript_available"),
            "intent_planner_delay_ms": self._delta_ms("transcript_available", "intent_detected"),
            "llm_request_to_first_token_ms": self._delta_ms("llm_request_started", "llm_first_token"),
            "llm_first_token_from_t0_ms": self._delta_ms("vad_end", "llm_first_token", allow_negative=True),
            "model_first_audio_from_t0_ms": self._delta_ms("vad_end", "model_first_audio", allow_negative=True),
            "tts_first_audio_from_first_token_ms": self._delta_ms("llm_first_token", "tts_first_audio"),
            "playback_startup_ms": self._delta_ms("tts_first_audio", "playback_started"),
            "first_audible_output_ms": self._delta_ms("vad_end", "playback_started"),
            "total_response_time_ms": self._delta_ms("vad_end", "completed"),
        }
        return {
            "turn_id": self.turn_id,
            "source": self.source,
            "t0_vad_end_monotonic": t0,
            "stages": dict(self.timestamps),
            "metrics_ms": metrics,
            "notes": list(self.notes),
        }


class VoiceLatencyRecorder:
    """Thread-safe per-turn timing recorder with JSONL output."""

    def __init__(
        self,
        sink: Callable[[dict], None] | None = None,
        log_path: str | Path | None = None,
    ) -> None:
        self._lock = threading.RLock()
        self._current: VoiceTurnMetrics | None = None
        self._sink = sink
        self.log_path = Path(log_path) if log_path else self.default_log_path()

    @staticmethod
    def default_log_path() -> Path:
        configured = os.getenv("JARVIS_VOICE_LATENCY_LOG", "").strip()
        if configured:
            return Path(configured)
        base = os.getenv("LOCALAPPDATA", "").strip()
        if base:
            return Path(base) / "JARVIS" / "voice_latency.jsonl"
        return Path.home() / ".jarvis" / "voice_latency.jsonl"

    @property
    def current(self) -> VoiceTurnMetrics | None:
        with self._lock:
            return self._current

    def start_turn(self, timestamp: float | None = None, source: str = "gemini-live") -> VoiceTurnMetrics:
        with self._lock:
            if self._current is not None:
                return self._current
            turn = VoiceTurnMetrics(turn_id=uuid.uuid4().hex, source=source)
            turn.mark("speech_started", timestamp)
            self._current = turn
            return turn

    def mark(self, stage: str, timestamp: float | None = None) -> VoiceTurnMetrics:
        with self._lock:
            turn = self._current or self.start_turn(timestamp)
            turn.mark(stage, timestamp)
            return turn

    def mark_vad_end(self, silence_delay_ms: float, timestamp: float | None = None) -> VoiceTurnMetrics:
        with self._lock:
            turn = self._current or self.start_turn(timestamp)
            turn.mark("vad_end", timestamp)
            turn.vad_silence_delay_ms = max(0.0, float(silence_delay_ms))
            return turn

    def complete(self, timestamp: float | None = None, note: str | None = None) -> dict | None:
        with self._lock:
            if self._current is None:
                return None
            turn = self._current
            if note:
                turn.notes.append(note)
            turn.mark("completed", timestamp)
            payload = turn.as_dict()
            self._current = None
        self._write(payload)
        return payload

    def _write(self, payload: dict) -> None:
        if self._sink:
            try:
                self._sink(payload)
            except Exception:
                pass
        try:
            self.log_path.parent.mkdir(parents=True, exist_ok=True)
            with self.log_path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(payload, separators=(",", ":")) + "\n")
        except Exception:
            # Telemetry must never break microphone, reasoning, or playback.
            pass


class VoiceLatencySummary:
    """Aggregate real recorded turns for a before/after report."""

    @staticmethod
    def from_records(records: list[dict]) -> dict:
        metric_names = (
            "vad_delay_ms", "stt_delay_ms", "intent_planner_delay_ms",
            "llm_first_token_from_t0_ms", "model_first_audio_from_t0_ms",
            "tts_first_audio_from_first_token_ms", "playback_startup_ms",
            "first_audible_output_ms", "total_response_time_ms",
        )
        summary: dict[str, dict[str, float | int | None]] = {}
        for name in metric_names:
            values = [
                float(record.get("metrics_ms", {}).get(name))
                for record in records
                if record.get("metrics_ms", {}).get(name) is not None
            ]
            summary[name] = {
                "count": len(values),
                "median_ms": sorted(values)[len(values) // 2] if values else None,
                "min_ms": min(values) if values else None,
                "max_ms": max(values) if values else None,
            }
        return summary
