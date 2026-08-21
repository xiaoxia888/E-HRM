"""E-HRM automation package."""

from pathlib import Path
import sys


_SOURCE_VERSION = "0.1.0"


def _application_version() -> str:
    bundle_root = getattr(sys, "_MEIPASS", None)
    if bundle_root:
        version_file = Path(bundle_root) / "ehrm" / "build_version.txt"
        try:
            value = version_file.read_text(encoding="utf-8").strip()
        except OSError:
            pass
        else:
            if value:
                return value
    return _SOURCE_VERSION


__version__ = _application_version()
