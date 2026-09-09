# J.A.R.V.I.S.

**Just A Rather Very Intelligent System**

A private, single-owner personal AI assistant for Windows — a faithful
transformation of the original **Brahma Echo** engineering foundation,
configured and branded for its owner: **Lucky**.

> **Made by Lucky** · Original project: *Brahma Echo* by Suryaansh Tiwari

---

## ⚠️ Private build — read this first

This is a **private personal build**. It is a transformation of the
source-available Brahma Echo project and is **not** a public distribution:

- `LICENSE` (Brahma Source-Available License) and `TRADEMARK.md` are kept
  byte-for-byte unchanged, together with all upstream attribution.
- If this repository is ever publicly visible, it must be made private again.
- See **[LEGAL.md](LEGAL.md)** for the full legal/attribution boundary.

---

## What this is

J.A.R.V.I.S. keeps the working architecture of Brahma Echo and presents it as
a single coherent personal assistant:

- Desktop HUD interface (dark, holographic styling, live system telemetry)
- Text + voice input and spoken responses (offline-first where practical)
- AI provider routing — local **Ollama** first, with optional cloud fallbacks
- Deterministic handling for system actions, math, memory and reminders
- One authoritative memory store, one config, one local database
- Windows computer control with validation and verification
- Secure device-trust gateway for remote/phone control (J.A.R.V.I.S. Connect)
- Optional smart-home, browser automation, calendar, files and office tools

## Quick start (Windows)

```bat
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python main.py
```

Configuration lives under `config/` (never commit `api_keys.json` —
see `.gitignore`). The assistant name defaults to **J.A.R.V.I.S.**; owner
profile is set during first-run onboarding.

## Status

This is the working-tree status of the transformation phases (see the branch
history for milestone commits):

| Area | Status |
| --- | --- |
| Original-source baseline | ✅ committed from upstream Brahma Echo |
| Legal / attribution boundary | ✅ `LEGAL.md`, LICENSE & TRADEMARK.md untouched |
| Product identity (J.A.R.V.I.S. / Made by Lucky) | ✅ transformed, internal identifiers preserved |
| Core, provider routing, HUD, memory, tools, auth, device trust | see branch history + tests |

## Original documentation

The upstream README and documentation are preserved verbatim in
[`docs/original/`](docs/original/README_Brahma_Echo.md) for reference and
attribution. Internal identifiers from the original architecture
(`brahma_connect`, `com.brahma.connect`, `_BRAHMA._tcp.local.`, config keys,
imports) are intentionally retained.

## License & attribution

- `LICENSE` — Brahma Source-Available License v1.0, Copyright (c) 2026 Suryaansh Tiwari.
- `TRADEMARK.md` — Brahma trademark notice.
- `LEGAL.md` — private-build boundary for this J.A.R.V.I.S. installation.
