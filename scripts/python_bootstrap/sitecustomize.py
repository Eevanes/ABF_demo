"""Process-local CPython 3.12 WMI fallback for Windows tool launchers."""

import sys

if sys.platform == "win32" and sys.version_info[:2] == (3, 12):
    sys.modules.setdefault("_wmi", None)
