"""Branding + legal-boundary tests for the private J.A.R.V.I.S. build.

Per the transformation rules:
- product-facing text must say J.A.R.V.I.S. / "Made by Lucky" where appropriate;
- LICENSE and TRADEMARK.md must remain unchanged;
- internal Brahma identifiers are allowed and expected to remain.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

ROOT = Path(__file__).resolve().parent.parent

PRODUCT_FILES = [
    "ui.py",
    "smart_home_page_new.py",
    "dashboard/static/app.html",
    "dashboard/static/login.html",
]

FORBIDDEN_PRODUCT_STRINGS = [
    "Brahma Echo",
    "BRAHMA ECHO",
    "I'm Brahma",
]


def test_license_and_trademark_preserved():
    license_text = (ROOT / "LICENSE").read_text(encoding="utf-8")
    assert license_text.startswith("Brahma Source-Available License")
    assert "Suryaansh Tiwari" in license_text

    trademark = (ROOT / "TRADEMARK.md").read_text(encoding="utf-8")
    assert "Brahma Trademark Notice" in trademark
    assert "Suryaansh Tiwari" in trademark


def test_legal_boundary_file_exists():
    legal = (ROOT / "LEGAL.md").read_text(encoding="utf-8")
    assert "J.A.R.V.I.S." in legal
    assert "Suryaansh Tiwari" in legal
    assert "private" in legal.lower()


def test_original_readme_preserved():
    original = ROOT / "docs" / "original" / "README_Brahma_Echo.md"
    assert original.exists()
    text = original.read_text(encoding="utf-8")
    assert "Brahma" in text


def test_new_readme_identity():
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    assert "J.A.R.V.I.S." in readme
    assert "Made by Lucky" in readme
    assert "LEGAL.md" in readme


def test_product_files_use_jarvis_branding():
    for rel in PRODUCT_FILES:
        text = (ROOT / rel).read_text(encoding="utf-8", errors="replace")
        # The intentional attribution line is exempt (legal requirement).
        text = text.replace("Original: Brahma Echo by Suryaansh Tiwari", "")
        for forbidden in FORBIDDEN_PRODUCT_STRINGS:
            assert forbidden not in text, f"{rel} still contains {forbidden!r}"
        assert "J.A.R.V.I.S." in text, f"{rel} should carry J.A.R.V.I.S. branding"


def test_core_identity_defaults():
    from core.identity import identity
    assert identity.get_assistant_name() == "J.A.R.V.I.S."
    assert identity.get_application_name() == "J.A.R.V.I.S."


def test_system_prompt_identity():
    prompt = (ROOT / "core" / "prompt.txt").read_text(encoding="utf-8")
    assert prompt.startswith("You are J.A.R.V.I.S.")


def test_internal_identifiers_preserved():
    """Brahma internal identifiers must survive (compatibility layer)."""
    main = (ROOT / "main.py").read_text(encoding="utf-8")
    assert "brahma_connect" in main or "brahma" in main.lower()
    gateway_config = (ROOT / "config" / "brahma_connect.json").read_text(encoding="utf-8")
    assert "_BRAHMA._tcp.local." in gateway_config
    assert (ROOT / "actions" / "brahma_connect.py").exists()


def test_made_by_lucky_footer_in_ui():
    ui = (ROOT / "ui.py").read_text(encoding="utf-8")
    assert "Made by Lucky" in ui
    assert "Suryaansh Tiwari" in ui  # original attribution kept alongside
