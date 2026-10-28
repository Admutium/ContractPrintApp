"""Product-specific portable settings; no import from other applications."""
from pathlib import Path
import sys

SETTINGS_OVERRIDE = None


def settings_path():
    if SETTINGS_OVERRIDE is not None:
        return Path(SETTINGS_OVERRIDE)
    base = Path(sys.executable).resolve().parent if getattr(sys, 'frozen', False) else Path(__file__).resolve().parent
    return base / 'user-data' / 'settings.json'
