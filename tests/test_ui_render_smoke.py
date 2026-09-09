"""Optional live-render smoke test for the J.A.R.V.I.S. HUD reactor.

Requires a working Qt runtime (PyQt6 + platform). On CI/sandboxes without a
usable Qt (e.g. missing system GL/fontconfig) these tests SKIP — the HUD is
then reported as STATIC PASS / UNVERIFIED rather than falsely "verified".

Set JARVIS_SKIP_RENDER=1 to force a skip.
"""

import os

import pytest

if os.environ.get("JARVIS_SKIP_RENDER") == "1":
    pytest.skip("render smoke disabled via env", allow_module_level=True)

try:
    from PyQt6.QtCore import Qt
    from PyQt6.QtGui import QColor, QImage
    from PyQt6.QtWidgets import QApplication
except Exception as exc:  # pragma: no cover
    pytest.skip(f"PyQt6 unavailable in this environment: {exc}", allow_module_level=True)

_app = None


def _qapp():
    global _app
    if _app is None:
        _app = QApplication.instance() or QApplication([])
    return _app


@pytest.fixture(scope="module")
def hud_widget():
    try:
        import ui as ui_mod
    except Exception as exc:  # pragma: no cover
        pytest.skip(f"ui module not importable here ({exc}); HUD runtime unverified", allow_module_level=False)
    _qapp()
    widget = ui_mod.HudCanvas("")
    widget.resize(300, 300)
    return widget


def _image_stats(image):
    image = image.convertToFormat(QImage.Format.Format_RGB32)
    colors = set()
    step = max(1, image.width() // 12)
    for x in range(0, image.width(), step):
        for y in range(0, image.height(), step):
            colors.add(image.pixelColor(x, y).rgb())
    return len(colors)


def test_hud_renders_reactor_in_each_state(hud_widget):
    """Render the reactor for every state and confirm actual painted output."""
    _qapp()
    for state in ["INITIALISING", "LISTENING", "THINKING", "PROCESSING",
                  "SPEAKING", "ERROR", "OFFLINE", "READY"]:
        hud_widget.state = state
        hud_widget.speaking = state == "SPEAKING"
        hud_widget._tick += 5
        image = hud_widget.grab().toImage()
        assert not image.isNull()
        assert image.width() >= 300 and image.height() >= 300
        distinct = _image_stats(image)
        assert distinct >= 4, f"{state}: reactor frame looks blank (only {distinct} colors)"
