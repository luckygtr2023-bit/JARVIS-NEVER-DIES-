"""Updater helpers for the J.A.R.V.I.S. private build.

This is a PRIVATE single-owner build transformed from Brahma Echo. Automatic
updates from the upstream Brahma repository are intentionally DISABLED: pulling
upstream would overwrite the local J.A.R.V.I.S. identity, branding and
configuration. `update_from_github` therefore always reports that no update is
available, and never touches the network or the git checkout.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path


def update_from_github(base_dir: Path) -> bool:
    """Return whether the app should restart after an update.

    Always returns False for the private build: upstream fast-forward updates
    are disabled because they would clobber the J.A.R.V.I.S. transformation.
    """
    return False


def restart_application(base_dir: Path) -> None:
    """Restart the application process (used by UI restart actions)."""
    if getattr(sys, "frozen", False):
        os.execv(sys.executable, [sys.executable, *sys.argv[1:]])
    else:
        os.execv(sys.executable, [sys.executable, str(Path(base_dir) / "main.py"), *sys.argv[1:]])
