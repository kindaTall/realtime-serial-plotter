"""Lazy loader for the sm_bedstate_driver module.

The driver lives in a sibling repo (ac_v2) and is published as a local
editable install. This helper centralises the import so callers get a
consistent error if it's missing.
"""

import importlib


_INSTALL_HINT = (
    "sm_bedstate_driver is not installed in this environment.\n"
    "Install it with:\n"
    "  pip install -e "
    "<path-to-ac_v2>/sm_bedstate_usb_driven/scripts/sm_bedstate_driver"
)


def load_driver():
    """Return the sm_bedstate_driver module (SMBedStateDriver + enums)."""
    try:
        return importlib.import_module("sm_bedstate_driver")
    except ImportError as e:
        raise ImportError(_INSTALL_HINT) from e
