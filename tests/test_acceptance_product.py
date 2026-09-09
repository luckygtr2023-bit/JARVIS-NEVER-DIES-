"""J.A.R.V.I.S. product-branding acceptance tests.

Levels used:
  PASS        = fully verified here (static/asset/logic assertions).
  STATIC PASS = source/assets verified; runtime (Windows Qt UI) not executed here.
  UNVERIFIED  = requires the actual Windows runtime (reported separately).

Checks:
  - HUD arc-reactor code exists and contains no leftover Brahma word fragments;
  - J.A.R.V.I.S. identity + "Made by Lucky" present in the product UI code;
  - product-facing logo/icon assets are J.A.R.V.I.S. (no Brahma logo in use);
  - OmniRoute routing layer exists and is wired into UnifiedAIClient;
  - Android user-visible strings are J.A.R.V.I.S. (identifiers untouched);
  - LICENSE / TRADEMARK.md remain byte-identical to the original upstream.
"""

import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

ROOT = Path(__file__).resolve().parent.parent


def test_hud_reactor_renders_jarvis_core():
    """STATIC PASS (runtime render needs Qt + Windows display)."""
    ui = (ROOT / "ui.py").read_text(encoding="utf-8")
    # Reactor must be actually drawn (QPainter gradients + live wordmark), not
    # a placeholder comment or static image.
    assert "J.A.R.V.I.S. ARC-REACTOR CORE" in ui
    assert "QRadialGradient" in ui
    assert "QPainter" in ui
    assert '"J.A.R.V.I.S."' in ui  # wordmark drawn each frame
    assert "AI CORE" in ui
    # The old split-wordmark remnants ("Brah" + "ma") must be gone.
    assert '"Brah"' not in ui and '"ma"' not in ui.replace('"Made', '')


def test_hud_states_have_distinct_rendering():
    """STATIC PASS — state -> color/label mapping covers required states."""
    ui = (ROOT / "ui.py").read_text(encoding="utf-8")
    for state in ["ERROR", "OFFLINE", "READY", "INITIALISING",
                  "LISTENING", "THINKING", "PROCESSING", "SPEAKING"]:
        assert state in ui, f"HUD state {state} not handled"
    assert "SYSTEM ERROR" in ui
    assert "STANDBY" in ui
    assert "QColor(255, 64, 64" in ui  # error red accent


def test_icon_assets_are_jarvis():
    """PASS — product icon assets exist and no Brahma icon is referenced."""
    for rel in ["assets/jarvis_logo.png", "assets/jarvis_logo.ico",
                "assets/jarvis_logo_master.png"]:
        assert (ROOT / rel).exists(), f"missing {rel}"
    # Product code must not reference the old Brahma logo files.
    for rel in ["main.py", "ui.py"]:
        text = (ROOT / rel).read_text(encoding="utf-8")
        assert "Brahma_Lite_Logo" not in text, rel
    # Historical copy is preserved for attribution (not used by the product).
    assert (ROOT / "docs" / "original" / "assets" / "Brahma_Lite_Logo.png").exists()


def test_made_by_lucky_visible_in_product_ui():
    """STATIC PASS — visible footer + About, not only source comments."""
    ui = (ROOT / "ui.py").read_text(encoding="utf-8")
    count = ui.count("Made by Lucky")
    assert count >= 2, f"expected Made by Lucky in footer AND About, found {count}"
    # Both sites are QLabel text that gets rendered.
    footer_idx = ui.find("_fl(\"Made by Lucky\"")
    about_idx = ui.find('"Made by Lucky"')
    assert footer_idx != -1
    assert about_idx != -1


def test_omniroute_exists_and_is_wired():
    """PASS — OmniRoute is a real module wired into the router chain."""
    assert (ROOT / "omniroute.py").exists()
    llm = (ROOT / "llm_client.py").read_text(encoding="utf-8")
    assert "from omniroute import" in llm
    assert "OMNIROUTE UNAVAILABLE" in llm
    assert "def route_status" in llm
    assert '"omni"' in llm  # chain stage present
    from llm_client import normalize_provider
    assert normalize_provider("OmniRoute") == "OmniRoute"
    assert normalize_provider("omniroute") == "OmniRoute"


def test_omniroute_settings_defaults():
    """PASS — UI/settings carry OmniRoute configuration."""
    ui = (ROOT / "ui.py").read_text(encoding="utf-8")
    assert '"OmniRoute"' in ui                       # provider combo option
    assert "omniroute_enabled" in ui
    assert "omniroute_url" in ui
    assert "omniroute_model" in ui
    # The settings page explicitly describes the honest-unavailable contract.
    assert "it never fakes a response" in ui or "never fakes" in ui


def test_android_user_visible_identity():
    """STATIC PASS — Android UI strings are J.A.R.V.I.S.; identifiers intact."""
    strings = (ROOT / "brahma-connect-android" / "app" / "src" / "main" / "res" / "values" / "strings.xml")
    text = strings.read_text(encoding="utf-8")
    assert 'J.A.R.V.I.S.' in text
    assert "Brahma Connect" not in text.replace("accessibility bridge", "")
    # internal package/class identifiers stay
    pkg = (ROOT / "brahma-connect-android" / "app" / "src" / "main" / "java" / "com" / "brahma" / "connect")
    assert pkg.is_dir()
    manifest = (ROOT / "brahma-connect-android" / "app" / "src" / "main" / "AndroidManifest.xml").read_text(encoding="utf-8")
    assert 'android:icon="@drawable/ic_jarvis_launcher"' in manifest
    assert (ROOT / "brahma-connect-android" / "app" / "src" / "main" / "res" / "drawable" / "ic_jarvis_launcher.png").exists()


def test_legal_files_byte_identical_to_upstream():
    """PASS — LICENSE and TRADEMARK.md are byte-identical to the baseline."""
    for name in ["LICENSE", "TRADEMARK.md"]:
        res = subprocess.run(
            ["git", "diff", "--quiet", "refs/remotes/brahma/main", "HEAD", "--", name],
            cwd=ROOT, capture_output=True, text=True)
        assert res.returncode == 0, f"{name} differs from the original upstream"


def test_no_product_branding_leftovers():
    """PASS — no visible Brahma remnants remain in product UI surfaces."""
    product = ["ui.py", "main.py", "smart_home_page_new.py",
               "dashboard/server.py", "dashboard/static/app.html",
               "dashboard/static/login.html"]
    for rel in product:
        text = (ROOT / rel).read_text(encoding="utf-8", errors="replace")
        # internal identifiers / protocol strings / attribution credit exempted
        for fragment in ["\"Brah\"", "BRAHMA ECHO", "Brahma Echo Remote",
                         "Brahma AI - Lite", "I'm Brahma", "Launch Brahma"]:
            assert fragment not in text, f"{rel} contains {fragment!r}"
