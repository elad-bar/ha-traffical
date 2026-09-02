"""Mount synthetic ``traffical`` package for the engine CLI (import side effect).

Import this module before any ``from traffical...`` so managers/models load
without executing the HA integration ``__init__``.
"""

from __future__ import annotations

import os
import sys
import types

_HERE = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(_HERE)
_ROOT = os.path.join(REPO_ROOT, "custom_components", "traffical")

if not (
    "traffical" in sys.modules and getattr(sys.modules["traffical"], "__path__", None)
):
    _pkg = types.ModuleType("traffical")
    _pkg.__file__ = os.path.join(_ROOT, "__init__.py")
    _pkg.__path__ = [_ROOT]  # type: ignore[attr-defined]
    _pkg.__package__ = "traffical"
    sys.modules["traffical"] = _pkg
