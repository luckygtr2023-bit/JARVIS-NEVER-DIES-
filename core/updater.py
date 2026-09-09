"""Updater UI glue for the J.A.R.V.I.S. private build.

Automatic updates are DISABLED by design. The upstream Brahma project used a
background checker that fetched the upstream repository hash and, on request,
hard-reset the local git checkout to upstream `origin/main`. For a private
transformed build that would silently overwrite the local J.A.R.V.I.S.
identity, branding and configuration — and a hard reset is destructive by
nature. Both entry points below are therefore inert and network-free.

The class/function names are preserved so existing UI call sites keep working.
"""

from __future__ import annotations

import sys
from pathlib import Path

try:
    from PyQt6.QtCore import QObject, pyqtSignal
    _HAS_PYQT = True
except Exception:  # pragma: no cover - non-UI contexts (tests, headless import)
    _HAS_PYQT = False

    class QObject:  # type: ignore[no-redef]
        pass

    def pyqtSignal(*_args, **_kwargs):  # type: ignore[misc,no-redef]
        def _decorate(_fn):
            return None
        return _decorate


class UpdateChecker(QObject):
    update_available_sig = pyqtSignal(str)

    def __init__(self, repo_owner: str = "", repo_name: str = "", branch: str = "main"):
        super().__init__()
        self.repo_owner = repo_owner
        self.repo_name = repo_name
        self.branch = branch

    def start(self) -> None:
        """No-op: private builds never check upstream for updates."""

    def stop(self) -> None:
        """No-op."""


def apply_update_and_restart() -> None:
    """No-op: private builds never apply upstream updates."""
    print("[Updater] Automatic updates are disabled for this private J.A.R.V.I.S. build.")
