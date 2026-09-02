"""English strings and translations stay in lockstep."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1] / "custom_components" / "traffical"
TRANSLATIONS = ROOT / "translations"


def _key_tree(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: _key_tree(child) for key, child in sorted(value.items())}
    if isinstance(value, list):
        return [_key_tree(item) for item in value]
    return None


def test_strings_match_en_translation() -> None:
    strings = json.loads((ROOT / "strings.json").read_text(encoding="utf-8"))
    en = json.loads((TRANSLATIONS / "en.json").read_text(encoding="utf-8"))
    assert strings == en


def test_locale_files_match_english_keys() -> None:
    en = json.loads((TRANSLATIONS / "en.json").read_text(encoding="utf-8"))
    expected = _key_tree(en)
    for path in sorted(TRANSLATIONS.glob("*.json")):
        locale = json.loads(path.read_text(encoding="utf-8"))
        assert _key_tree(locale) == expected, path.name
