# J.A.R.V.I.S. — Private Build Legal & Attribution Notice

## Project identity

- **Product-facing name:** J.A.R.V.I.S. (Just A Rather Very Intelligent System)
- **Private build for:** Lucky
- **Footer line used in product UI:** Made by Lucky
- **Repository:** private destination for a single-user personal build

## Original software (unchanged, all rights belong to the original author)

- **Original project:** Brahma Echo
- **Original author / copyright holder:** Suryaansh Tiwari
- **Upstream source:** https://github.com/titechprabhasolutions/Brahma-Echo
- **License:** Brahma Source-Available License, Version 1.0 — see `LICENSE` (kept byte-for-byte unchanged in this repository).
- **Trademarks:** see `TRADEMARK.md` (kept byte-for-byte unchanged). `Brahma`, `Brahma AI`, the Brahma logo and related brand assets are trademarks or trade dress associated with Suryaansh Tiwari.

## What this private build is

This repository is a **private, personal, single-owner transformation** of the Brahma Echo
source code into a locally-run assistant named J.A.R.V.I.S. (Just A Rather Very Intelligent
System), configured for its owner, Lucky.

Under section 1 of the Brahma Source-Available License, personal use, study, modification and
private deployment of the source are permitted, provided the license terms are respected:

- This is **not** a public release or redistribution of a modified fork under a new name.
- If this repository is ever made publicly visible, it **must** be made private again, because
  this build carries a product name (J.A.R.V.I.S.) that is not the upstream project name.
- No authorship, ownership, sponsorship or endorsement by the original author is claimed.

## Attribution kept in the source tree

The following legally required notices are preserved and are **not** modified:

- `LICENSE` — original Brahma Source-Available License text.
- `TRADEMARK.md` — original Brahma trademark notice.
- Copyright notices inside source files, file headers and version metadata that attribute the
  software to Suryaansh Tiwari (e.g. `version.txt` Windows version metadata).
- `docs/original/` — upstream documentation (including the original Brahma Echo README)
  preserved verbatim for reference and attribution.
- In-product credit line: "Original: Brahma Echo by Suryaansh Tiwari" where the product footer
  appears.

## What may legally stay / change

- The product-facing name J.A.R.V.I.S., the line "Made by Lucky", and the assistant
  configuration are applied **only** where they do not remove or replace upstream attribution.
- Internal identifiers from the original architecture are intentionally retained:
  `brahma_connect/`, `actions/brahma_connect.py`, `com.brahma.connect`,
  `_BRAHMA._tcp.local.`, internal config keys, database identifiers, internal imports and
  protocol strings. These are implementation identifiers, not product branding.
- The upstream device gateway subsystem keeps its internal identifiers
  (`brahma_connect`, `com.brahma.connect`, `_BRAHMA._tcp.local.`). Product-facing UI labels
  for the gateway feature use "J.A.R.V.I.S. Connect"; the upstream "Brahma Connect" name
  appears only in historical/technical documentation and in `docs/original/`.

## Third-party components

Third-party libraries used by this project are governed by their own licenses
(see `requirements.txt` and upstream documentation). No third-party license text was removed.
