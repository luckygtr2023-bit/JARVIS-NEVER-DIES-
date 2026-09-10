# J.A.R.V.I.S. voice latency

## Audited pipeline

The Windows voice session is not a record-then-transcribe application. The
existing live path is:

```text
sounddevice.InputStream (16 kHz, 16-bit mono, 512-frame / 32 ms callbacks by default)
  -> RMS echo gate + local observer VAD
  -> continuous Gemini Live realtime PCM input
  -> Gemini Live input transcription (streaming STT)
  -> Gemini Live server intent/tool/reasoning/LLM
  -> Gemini Live native PCM response (streaming TTS)
  -> one persistent sounddevice.RawOutputStream (24 kHz)
```

The local RMS observer does not replace Gemini Live's server activity detector
and does not stop PCM input. Its purpose is to measure the actual local end of
speech and tune the server hangover. The text-only/disconnected path is:

```text
text/transcribed request -> deterministic intent classifier
  -> fast direct stream for knowledge/reasoning/chitchat
  -> Local Ollama -> OmniRoute -> OpenRouter fallback stream
  -> sentence boundary -> serial Edge TTS chunk -> Windows MCI playback
```

Research, browser automation, tool calls, and multi-step work stay on the
existing full reasoning/planner path. They are not sent through the fast path.

## Measurements

`VoiceLatencyRecorder` writes one JSON object per completed live turn to:

- `%LOCALAPPDATA%\\JARVIS\\voice_latency.jsonl` on Windows, or
- `JARVIS_VOICE_LATENCY_LOG` when explicitly configured.

It records monotonic timestamps for speech onset, local VAD end (T0), first
input transcription, the local intent-observer classification, LLM request
start, first native model output, first TTS audio, first output-stream write
(T6), and turn completion. Gemini Live's internal server planner is not
exposed as a separate client event, so it is documented in the turn notes
rather than guessed. Missing stages remain `null`; they are never filled with
estimates.

The output includes these measured fields:

- `vad_delay_ms`
- `stt_delay_ms`
- `intent_planner_delay_ms`
- `llm_first_token_from_t0_ms` (null when the Live SDK emits no output text transcription)
- `model_first_audio_from_t0_ms`
- `tts_first_audio_from_first_token_ms`
- `playback_startup_ms`
- `first_audible_output_ms`
- `total_response_time_ms`

A real before/after table must be made from two JSONL captures on the same
Windows machine and workload. This sandbox has no microphone, sounddevice,
PyQt, google-genai, Edge TTS, audio output, or provider credentials, so it
cannot honestly produce hardware/provider latency values.

## Configurable VAD

The defaults are intentionally conservative while reducing unnecessary
silence hangover:

| Environment variable | Default | Meaning |
| --- | ---: | --- |
| `JARVIS_VOICE_SILENCE_MS` | `320` | required quiet period before T0 |
| `JARVIS_VOICE_ONSET_MS` | `64` | voiced confirmation before speech start |
| `JARVIS_VOICE_MIN_SPEECH_MS` | `128` | reject shorter noise bursts |
| `JARVIS_VOICE_RMS_THRESHOLD` | `10` | base int16 RMS threshold |
| `JARVIS_VOICE_ECHO_RMS_THRESHOLD` | `1200` | threshold while J.A.R.V.I.S. is speaking |
| `JARVIS_VOICE_NOISE_MULTIPLIER` | `2.5` | adaptive noise-floor multiplier |
| `JARVIS_VOICE_CHUNK_FRAMES` | `512` | microphone/output callback block size |
| `JARVIS_VOICE_BARGE_IN` | `0` | opt-in local buffered-audio interruption |

The Gemini Live config receives the same speech onset padding and silence
hangover when the installed google-genai SDK exposes realtime activity
configuration. Older SDKs use their own defaults without preventing startup.

## Streaming changes

- Gemini Live remains the preferred voice path and already streams STT and
  native response audio. Output is queued directly into a persistent raw audio
  stream; it does not write a response file.
- The disconnected text fallback now consumes OpenAI-compatible SSE deltas
  from Ollama, OmniRoute, or OpenRouter and sends completed sentences to TTS
  serially. This begins the first sentence before the model's full response
  exists.
- OmniRoute's configured chat endpoint remains the Windows-local
  `http://localhost:20128/chat/completions` default. Android does not use this
  localhost route and continues through the trusted LAN gateway.
- OpenRouter and OmniRoute keep a reusable streaming HTTP session. Gemini Live
  keeps its existing long-lived session across turns.
- Edge TTS's current Windows/MCI adapter is still file-based per sentence;
  it is chunked at the sentence boundary but is not falsely described as
  byte-streaming. Gemini Live is the true streaming TTS path.

## Realtime provider decision

The existing Gemini Live native-audio session is already the optional realtime
speech-to-speech provider in this architecture. It is retained rather than
adding another SDK or hard-coded credential. If it is unavailable, the
existing configured text-provider chain and Edge TTS fallback remain
available, with honest errors. No new dependency or secret was added.

## Interruption safety

True server-side Gemini response cancellation is SDK-version dependent and is
not enabled by default. With `JARVIS_VOICE_BARGE_IN=1`, confirmed speech onset
clears already-buffered local output and stops the file-based fallback audio;
the in-flight Gemini server turn is not claimed to be cancelled. This avoids
fragile accidental interruptions in the default demonstration configuration.
