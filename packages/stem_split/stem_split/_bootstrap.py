"""Ensure repo-root ``config`` is importable when PYTHONPATH is unset."""

from __future__ import annotations

import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[3]


def ensure_config_importable() -> None:
    root_s = str(_REPO_ROOT)
    if root_s not in sys.path:
        sys.path.insert(0, root_s)
    try:
        from dotenv import load_dotenv

        load_dotenv(_REPO_ROOT / ".env")
    except ImportError:
        pass
