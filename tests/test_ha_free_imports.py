"""HA-free import boundary for models / managers used by engine."""

from __future__ import annotations

import importlib
from pathlib import Path
import re
import sys

import pytest

from custom_components.traffical.common.consts import PLATFORMS

_REPO = Path(__file__).resolve().parents[1]
_ENGINE = _REPO / "engine"
_HA_FREE_MODULES = (
    "traffical.models.exceptions",
    "traffical.models.coordinates",
    "traffical.models.entity_specs",
    "traffical.models.entity_values",
    "traffical.models.ride_calendar",
    "traffical.models.ride_window",
    "traffical.models.rides",
    "traffical.models.stations",
    "traffical.managers.api_client",
    "traffical.managers.identity_client",
    "traffical.managers.mobile_client",
    "traffical.managers.signalr_client",
    "traffical.managers.store",
    "traffical.common.consts",
    "traffical.common.helpers",
)


def _mount_ha_free() -> None:
    sys.path.insert(0, str(_ENGINE))
    for name in list(sys.modules):
        if name == "traffical" or name.startswith("traffical."):
            del sys.modules[name]
        if name == "ha_free_path":
            del sys.modules[name]
    import ha_free_path  # noqa: F401


def test_ha_free_modules_import_without_homeassistant() -> None:
    had_ha = "homeassistant" in sys.modules
    _mount_ha_free()
    before = {
        k for k in sys.modules if k == "homeassistant" or k.startswith("homeassistant.")
    }
    for mod_name in _HA_FREE_MODULES:
        mod = importlib.import_module(mod_name)
        assert mod is not None
        assert "custom_components" in (mod.__file__ or "").replace("\\", "/")
    after = {
        k for k in sys.modules if k == "homeassistant" or k.startswith("homeassistant.")
    }
    assert after == before or had_ha
    newly = after - before
    assert not newly, f"HA-free import pulled in: {newly}"


def test_platforms_use_common_entity_setup() -> None:
    root = _REPO / "custom_components" / "traffical"
    for name in PLATFORMS:
        text = (root / f"{name}.py").read_text(encoding="utf-8")
        assert "from .common.entity_setup import async_setup_entities" in text
        assert "async_setup_entities(" in text


def test_platforms_hold_no_per_entity_branching() -> None:
    """Per-key logic belongs in the catalog, not in the platform files."""
    root = _REPO / "custom_components" / "traffical"
    for name in PLATFORMS:
        text = (root / f"{name}.py").read_text(encoding="utf-8")
        assert "entity_key" not in text, name
        assert not re.search(r"spec\.key\s*==", text), name


@pytest.mark.parametrize("mod_name", _HA_FREE_MODULES)
def test_ha_free_module_source_has_no_homeassistant_import(mod_name: str) -> None:
    rel = mod_name.removeprefix("traffical.").replace(".", "/") + ".py"
    path = _REPO / "custom_components" / "traffical" / rel
    text = path.read_text(encoding="utf-8")
    assert not re.search(
        r"^(?:from|import)\s+homeassistant\b", text, re.MULTILINE
    ), f"{path} imports homeassistant"
