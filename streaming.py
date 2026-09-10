"""Small dependency-free helpers for low-latency text streaming.

The application already has streaming audio through Gemini Live.  These
helpers cover the text fallback path without introducing another SDK: they
parse standard OpenAI-compatible SSE responses and turn token fragments into
natural sentence-sized TTS chunks.
"""

from __future__ import annotations

import json
import re
from typing import Iterable, Iterator, Any


_SENTENCE_RE = re.compile(r"(?<=[.!?])(?:[\"'”’)]*)?(?=\s|$)|\n{2,}")


def iter_sse_content(response: Any) -> Iterator[str]:
    """Yield text deltas from an OpenAI-compatible streaming response.

    Providers send ``data: {json}`` lines followed by ``data: [DONE]``.  A
    small number of local gateways return a normal JSON response even when a
    stream was requested, so that shape is accepted as a compatibility
    fallback.  No response or credential data is logged here.
    """
    iterator = getattr(response, "iter_lines", None)
    if iterator is None:
        try:
            data = response.json()
            content = data.get("choices", [{}])[0].get("message", {}).get("content", "")
            if content:
                yield str(content)
            return
        except Exception as exc:
            raise RuntimeError(f"Streaming response had no readable body: {exc}") from exc

    for raw_line in iterator(decode_unicode=True):
        if raw_line is None:
            continue
        if isinstance(raw_line, bytes):
            raw_line = raw_line.decode("utf-8", "replace")
        line = str(raw_line).strip()
        if not line or line.startswith(":"):
            continue
        if line.startswith("data:"):
            line = line[5:].strip()
        if not line or line == "[DONE]":
            if line == "[DONE]":
                break
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            # A few proxies split an SSE JSON object over adjacent lines.  A
            # malformed event is ignored rather than turned into fake speech.
            continue
        choices = payload.get("choices") or []
        if not choices:
            continue
        choice = choices[0] or {}
        delta = choice.get("delta") or {}
        content = delta.get("content")
        if content is None:
            content = choice.get("text")
        if content:
            yield str(content)


class SentenceChunker:
    """Buffer token fragments and emit natural, non-overlapping TTS chunks."""

    def __init__(self, max_chars: int = 260) -> None:
        if max_chars < 32:
            raise ValueError("max_chars must be at least 32")
        self.max_chars = max_chars
        self._buffer = ""

    def feed(self, text: str) -> list[str]:
        self._buffer += str(text or "")
        return self._drain(final=False)

    def flush(self) -> list[str]:
        return self._drain(final=True)

    def _drain(self, final: bool) -> list[str]:
        emitted: list[str] = []
        while self._buffer:
            match = _SENTENCE_RE.search(self._buffer)
            cut = match.end() if match else -1
            if cut <= 0 and len(self._buffer) > self.max_chars:
                cut = self._safe_cut(self._buffer)
            if cut <= 0:
                break
            chunk = self._buffer[:cut].strip()
            self._buffer = self._buffer[cut:].lstrip()
            if chunk:
                emitted.append(chunk)
        if final and self._buffer.strip():
            emitted.append(self._buffer.strip())
            self._buffer = ""
        return emitted

    def _safe_cut(self, text: str) -> int:
        limit = min(self.max_chars, len(text))
        split = text.rfind(" ", 0, limit + 1)
        return split if split >= 32 else limit


def stream_text_to_tts(
    token_stream: Iterable[str],
    speak_chunk,
    *,
    on_text=None,
    chunker: SentenceChunker | None = None,
) -> str:
    """Consume a token stream and synchronously play each ready TTS chunk.

    ``speak_chunk`` is deliberately called serially.  This prevents a short
    sentence from being cut off by the next sentence and makes interruption
    behavior deterministic.  The returned text is the exact concatenation of
    received chunks, not generated or repaired text.
    """
    chunker = chunker or SentenceChunker()
    received: list[str] = []
    for token in token_stream:
        token = str(token or "")
        if not token:
            continue
        received.append(token)
        if on_text:
            on_text(token)
        for chunk in chunker.feed(token):
            speak_chunk(chunk)
    for chunk in chunker.flush():
        speak_chunk(chunk)
    return "".join(received).strip()


class InterruptibleAudioBuffer:
    """Thread-safe generation buffer used by optional safe barge-in support."""

    def __init__(self) -> None:
        from collections import deque
        from threading import Lock
        self._items = deque()
        self._lock = Lock()
        self._generation = 0

    @property
    def generation(self) -> int:
        with self._lock:
            return self._generation

    def put(self, chunk: bytes) -> int:
        with self._lock:
            generation = self._generation
            self._items.append((generation, bytes(chunk)))
            return generation

    def interrupt(self) -> int:
        with self._lock:
            self._generation += 1
            self._items.clear()
            return self._generation

    def get(self) -> bytes | None:
        with self._lock:
            if not self._items:
                return None
            generation, chunk = self._items.popleft()
            if generation != self._generation:
                return None
            return chunk

    def __len__(self) -> int:
        with self._lock:
            return len(self._items)
