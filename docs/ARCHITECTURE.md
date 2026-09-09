# J.A.R.V.I.S. — Architecture Map (internal working document)

Private transformation of Brahma Echo. **Internal identifiers (brahma_connect,
`com.brahma.connect`, `_BRAHMA._tcp.local.`, config keys) are intentionally
unchanged** — only product-facing identity says J.A.R.V.I.S.

## Entry points

| Path | Role |
| --- | --- |
| `main.py` | Desktop app entry: PyQt6 UI (`BrahmaUI`), `BrahmaLive` core loop, tool registry, wake words, Gemini live/audio + provider fallback, dashboard/connect startup |
| `ui.py` | Main HUD interface (dark, telemetry panels, chat feed, task workspace, settings, onboarding) |
| `dashboard/server.py` + `dashboard/static/` | Local HTTP/WebSocket remote dashboard (FastAPI, AES session) |
| `brahma_connect/service.py` + `gateway/` | Device-trust gateway: pairing (TTL codes), registry (`config/brahma_connect/devices.json`), auth (hashed secrets, constant-time), command router, discovery (`_BRAHMA._tcp.local.`), WebSocket hub |
| `brahma-connect-android/` | Android companion (Brahma Connect) — secondary phase |
| `smart_home/`, `homescreen background/`, `extra/`, `discord_bot.py`, `updater.py` | Optional/extras (updater intentionally disabled for private build) |

## AI providers (Phase 5)

- `or_client.py` — OpenRouter client (remote; HTTP-Referer/X-Title set to this build).
- `llm_client.py` — `UnifiedAIClient` facade. Canonical providers: `Local` (Ollama/LM Studio, default local endpoint `http://localhost:11434/v1`, model `llama3.2`), `OpenRouter`, `Gemini`. Settings keys: `default_ai_provider`, `local_ai_url`, `local_ai_model`, `auto_provider_switch`. Auto-switch tries the alternate class once, then raises `AI UNAVAILABLE — <detail>` (never fakes success).
- Gemini direct paths in `main.py`: `_gemini_text_reply`, live audio session in `BrahmaLive`.

## Core pipeline (`main.py`)

User text → `_on_text_command` → deterministic direct handlers (smart home,
Brahma Connect devices, screen, attention/reply modes, plugin dispatch) → task
plan/workspace → `_fallback_reply` (Gemini → UnifiedAIClient with
Local/OpenRouter) → UI `write_log` + task workspace update + optional speech.

## Other subsystems

- Memory: `memory/memory_manager.py` (single `memory/long_term.json`, categories, extraction), `workspace_store.py` (SQLite conversation store).
- Actions: `actions/` modules; entry `actions/brahma_connect.py` wraps gateway for tools.
- Windows tools: computer control/settings, open_app, system monitor, file ops, browser_control, office/docs/pdf generators.
- Config: `config/` (`api_keys.json` + `app_settings.json` + `brahma_connect.json` are runtime/gitignored; `.gitignore` guards secrets).

## Runtime data (all gitignored)

`config/api_keys.json`, `config/app_settings.json`, `config/brahma_connect/devices.json`,
`config/workspace_store.sqlite3*`, `memory/long_term.json`, `memory/calendar_events.json`,
logs under `%LOCALAPPDATA%\JARVIS\`.

## Tests

| File | Covers |
| --- | --- |
| `tests/test_brahma_connect.py`, `test_brahma_connect_actions.py` | protocol, device registry/auth, pairing TTL, capability manager, connect action wrappers (original, passing) |
| `tests/test_ai_providers.py` | provider routing/fallback/honest errors (new) |
| `tests/test_branding_legal.py` | branding + legal boundary (new) |

## Windows-only (not runnable in the Linux sandbox)

PyQt6 HUD rendering, voice (sounddevice/live audio), gesture/screen (mediapipe/OpenCV),
Windows process/window control, EXE packaging. These remain **UNVERIFIED** here.
