"""Print a measured before/after voice latency comparison.

Usage:
    python tools/voice_latency_report.py baseline.jsonl final.jsonl

The script refuses to invent missing values and prints UNVERIFIED for a
missing stage/file. It is intentionally standard-library-only so it can run on
the Windows demonstration machine before optional app dependencies load.
"""

from __future__ import annotations

import json
import statistics
import sys
from pathlib import Path

METRICS = (
    ("vad_delay_ms", "VAD delay"),
    ("stt_delay_ms", "STT delay"),
    ("intent_planner_delay_ms", "Intent/planner delay"),
    ("llm_first_token_from_t0_ms", "LLM first token from T0"),
    ("model_first_audio_from_t0_ms", "Model first audio from T0"),
    ("tts_first_audio_from_first_token_ms", "TTS first audio"),
    ("playback_startup_ms", "Playback startup"),
    ("first_audible_output_ms", "First audible output"),
    ("total_response_time_ms", "Total response time"),
)


def load(path: str) -> list[dict]:
    p = Path(path)
    if not p.exists():
        return []
    rows = []
    for line in p.read_text(encoding="utf-8").splitlines():
        try:
            obj = json.loads(line)
            if isinstance(obj, dict):
                rows.append(obj)
        except json.JSONDecodeError:
            continue
    return rows


def median(rows: list[dict], key: str) -> float | None:
    values = [
        float(row.get("metrics_ms", {}).get(key))
        for row in rows
        if row.get("metrics_ms", {}).get(key) is not None
    ]
    return statistics.median(values) if values else None


def fmt(value: float | None) -> str:
    return "UNVERIFIED" if value is None else f"{value:.1f} ms"


def main(argv: list[str]) -> int:
    if len(argv) != 3:
        print(__doc__.strip())
        return 2
    before = load(argv[1])
    after = load(argv[2])
    print(f"Measured turns: before={len(before)} after={len(after)}")
    print("Metric | Before median | After median | Change")
    print("--- | ---: | ---: | ---:")
    for key, label in METRICS:
        old = median(before, key)
        new = median(after, key)
        if old is None or new is None:
            change = "UNVERIFIED"
        else:
            change = f"{new - old:+.1f} ms"
        print(f"{label} | {fmt(old)} | {fmt(new)} | {change}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
