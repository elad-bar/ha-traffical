"""Changelog sections for releases and manifest version parity."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EXTRACT_PATH = ROOT / "scripts" / "extract_changelog_section.py"
MANIFEST = ROOT / "custom_components" / "traffical" / "manifest.json"
CHANGELOG = ROOT / "CHANGELOG.md"


def _load_extract():
    spec = importlib.util.spec_from_file_location(
        "extract_changelog_section", EXTRACT_PATH
    )
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


def test_manifest_version_has_changelog_section() -> None:
    version = json.loads(MANIFEST.read_text(encoding="utf-8"))["version"]
    extract = _load_extract()
    body = extract.extract_changelog_section(
        CHANGELOG.read_text(encoding="utf-8"), version
    )
    assert "### Added" in body or "### Changed" in body or "### Fixed" in body


def test_extract_changelog_section_stops_at_next_version() -> None:
    extract = _load_extract()
    text = """# Changelog

## [0.1.1] - 2026-01-02

### Added

- First item only in 0.1.1

## [0.1.0] - 2026-01-01

### Added

- Older scaffolding section
"""
    body = extract.extract_changelog_section(text, "0.1.1")
    assert "First item only in 0.1.1" in body
    assert "Older scaffolding section" not in body
