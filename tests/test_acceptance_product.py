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


# ---------------------------------------------------------------------------
# HUD dashboard / chat redesign milestone (reactor, panels, navigation, layout)
# ---------------------------------------------------------------------------

def test_dashboard_layout_uses_window_space():
    """STATIC PASS — dashboard centre is a populated command-centre layout
    (telemetry panels, live reactor, AI-router panel, quick actions, input bar),
    no longer a mostly-hidden blank stage."""
    ui = (ROOT / "ui.py").read_text(encoding="utf-8")
    assert "SYSTEM TELEMETRY" in ui              # live stat cards
    assert "ReactorArena" in ui                  # reactor stage panel
    assert "AI ROUTER" in ui                     # real provider status panel
    assert "J.A.R.V.I.S. LINK" in ui             # link/status card
    assert "QSplitter" in ui                     # re-sizable hero columns
    assert "hero.setSizes(" in ui
    assert "_refresh_dashboard_link_values" in ui
    assert "self.hud.hide()" not in ui           # reactor is visible
    assert "stage.addWidget(self._core_status_lbl)" in ui
    assert "_build_command_row()" in ui          # bottom voice/input bar


def test_dashboard_quick_actions():
    """STATIC PASS — quick-action chips exist for chat/voice/example prompts."""
    ui = (ROOT / "ui.py").read_text(encoding="utf-8")
    for marker in ["What can you do?", "Today's briefing", "Open chat",
                   "Voice / mute", "System status"]:
        assert marker in ui, marker
    assert "self._toggle_mute()" in ui           # voice control wired
    assert "_switch_to(\"chat\")" in ui or '_switch_to("chat")' in ui


def test_chat_ui_content():
    """STATIC PASS — chat surfaces: full-page Chat + dashboard rail mirror
    with history, message bubbles and empty-state quick actions."""
    ui = (ROOT / "ui.py").read_text(encoding="utf-8")
    assert '"chat": 4' in ui                     # Chat tab maps to the chat page
    assert "InlineChatWorkspace" in ui
    assert "command_submitted" in ui
    assert "Try asking J.A.R.V.I.S." in ui
    assert "Create Presentation" in ui
    assert "ChatBubble" in ui
    assert "_rail_chat" in ui                    # dashboard chat mirror
    assert "_feed_only" in ui                    # mirror never double-writes store
    assert "_chat_mirrors" in ui
    assert "reload_active_conversation" in ui


def test_made_by_lucky_rendered_sites():
    """STATIC PASS — 'Made by Lucky' appears in rendered widgets across the
    chrome: top taskbar, global footer, dashboard link card and About."""
    ui = (ROOT / "ui.py").read_text(encoding="utf-8")
    assert ui.count("Made by Lucky") >= 4


def test_responsive_layout_no_collapse():
    """STATIC PASS — rails are collapsible and the hero uses a splitter with
    stretch factors + size floors so no giant empty regions form."""
    ui = (ROOT / "ui.py").read_text(encoding="utf-8")
    assert "_left_collapsed" in ui and "_right_collapsed" in ui
    assert "56 if self._left_collapsed else _LEFT_W" in ui
    assert "56 if self._right_collapsed else _RIGHT_W" in ui
    assert "hero.setStretchFactor(1, 1)" in ui   # reactor column takes the space
    assert "arena.setMinimumSize(300, 260)" in ui
    assert "left_col.setMaximumWidth(252)" in ui
    assert "right_col.setMaximumWidth(286)" in ui
    assert 'setMinimumSize(_MIN_W, _MIN_H)' in ui
    assert "_mw < 1450 and not self._right_collapsed" in ui   # auto rail collapse
    assert "_mw < 1240 and not self._left_collapsed" in ui


# ---------------------------------------------------------------------------
# HUD final visual correction (Devanagari-free, minimal background)
# ---------------------------------------------------------------------------

DEVANAGARI_TEXT_FILES = [
    "ui.py", "main.py", "omniroute.py", "llm_client.py", "smart_home_page_new.py",
    "workspace_store.py", "gesture_utils.py",
]

def test_no_devanagari_in_product_code():
    """PASS - zero Devanagari characters (U+0900..U+097F) in product code."""
    import unicodedata
    for rel in DEVANAGARI_TEXT_FILES + [
        "dashboard/server.py", "or_client.py", "setup.py", "requirements.txt",
    ]:
        text = (ROOT / rel).read_text(encoding="utf-8", errors="replace")
        bad = [ch for ch in text if "ऀ" <= ch <= "ॿ"]
        assert not bad, f"{rel} contains Devanagari: {bad}"
    # no runtime Unicode escapes for Devanagari remain
    for rel in ("ui.py", "main.py"):
        text = (ROOT / rel).read_text(encoding="utf-8")
        assert "\\u09" not in text, f"{rel} still has a \\u09 escape"


def test_jarvis_name_uses_latin_only():
    """PASS - every wordmark rendered by the UI is the deterministic Latin
    string J.A.R.V.I.S.; the Devanagari जार्विस must not appear."""
    ui = (ROOT / "ui.py").read_text(encoding="utf-8")
    assert "जार्विस" not in ui
    # the launcher core wordmark and the reactor wordmark are literal Latin text
    assert 'drawText(QRectF(cx - 27, cy - 9, 54, 18), Qt.AlignmentFlag.AlignCenter, "J.A.R.V.I.S.")' in ui
    assert '"J.A.R.V.I.S."' in ui
    assert "Nirmala UI" not in ui          # Hindi font no longer used
    # CommandBar mini-logo uses the deterministic app logo pixmap, not a glyph
    assert "logo_lbl.setPixmap(_logo_pixmap(22))" in ui


def test_logo_assets_metadata_clean_and_latin():
    """PASS - logo rasters are freshly generated, metadata-free and valid."""
    import struct, pathlib
    def text_chunks(path: pathlib.Path):
        data = path.read_bytes()
        assert data[:8] == b"\x89PNG\r\n\x1a\n", f"{path} not a PNG"
        pos, out = 8, []
        while pos < len(data):
            ln = struct.unpack(">I", data[pos:pos + 4])[0]
            typ = data[pos + 4:pos + 8].decode("latin-1")
            if typ in ("tEXt", "iTXt", "zTXt"):
                out.append(typ)
            pos += 12 + ln
        return out
    for rel in ("assets/jarvis_logo.png", "assets/jarvis_logo_master.png",
                "brahma-connect-android/app/src/main/res/drawable/ic_jarvis_launcher.png"):
        p = ROOT / rel
        assert p.exists(), rel
        assert not text_chunks(p), f"{rel} carries embedded text metadata"
    from PIL import Image
    ico = Image.open(ROOT / "assets/jarvis_logo.ico")
    sizes = sorted(ico.ico.sizes())
    assert sizes == [(16,16),(24,24),(32,32),(48,48),(64,64),(128,128),(256,256)], sizes


def test_hud_background_minimal():
    """STATIC PASS - the HUD backdrop is a restrained dark canvas: heavy grid,
    equalizer 'signal noise', corner brackets and dense halo rings removed."""
    ui = (ROOT / "ui.py").read_text(encoding="utf-8")
    for removed in ("fine tactical grid", "corner brackets", "signal noise",
                    "for i in range(10):", "for side in (-1, 1):"):
        assert removed not in ui, f"busy decoration still present: {removed}"
    for kept in ("subtle pulse rings", "spinning arc rings", "single thin scanner arc",
                 "restrained ambient glow", "thin crosshair", "tick marks (thin, faint)"):
        assert kept in ui, f"minimal-geometry section missing: {kept}"
    assert "self.hud.hide()" not in ui
    assert "J.A.R.V.I.S." in ui            # branding kept
    assert 'word_font = QFont("Segoe UI", 8' in ui
