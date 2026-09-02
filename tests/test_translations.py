"""English strings and translations stay in lockstep."""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "custom_components" / "traffical"


def test_strings_match_en_translation() -> None:
    strings = json.loads((ROOT / "strings.json").read_text(encoding="utf-8"))
    en = json.loads((ROOT / "translations" / "en.json").read_text(encoding="utf-8"))
    assert strings == en
