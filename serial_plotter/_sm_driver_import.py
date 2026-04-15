"""Lazy loader for the external sm_bedstate_driver stub.

The stub lives in a sibling repo with no packaging, so we try a normal
import first and fall back to inserting a known path on sys.path. Override
the path with env var SM_BEDSTATE_DRIVER_PATH.
"""

import importlib
import os
import sys
from pathlib import Path

_DEFAULT_PATH = (
    "/Users/nils/repos/ac_v2/sm_bedstate_usb_driven/scripts/sm_bedstate_driver"
)


def load_driver():
    """Return the sm_bedstate_driver module (exposes SMBedStateDriver, enums)."""
    try:
        return importlib.import_module("sm_bedstate_driver")
    except ImportError:
        candidate = Path(os.environ.get("SM_BEDSTATE_DRIVER_PATH", _DEFAULT_PATH))
        if candidate.is_dir() and str(candidate) not in sys.path:
            sys.path.insert(0, str(candidate))
        return importlib.import_module("sm_bedstate_driver")
