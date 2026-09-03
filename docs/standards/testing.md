# Testing standards

Run `pytest` from the **repo root**. There is no coverage gate.

[CI](ci.md) (Ubuntu, Python 3.13) is the authority for the **full** suite, including Home Assistant plugin tests.

## Windows vs Linux

[`tests/conftest.py`](../../tests/conftest.py) loads `pytest_homeassistant_custom_component` only when `fcntl` exists. Native Windows Python does not; HA-runtime modules listed in `_HASS_TEST_FILES` are skipped.

**HA plugin skip list** (`_HASS_TEST_FILES`): `test_config_flow.py`, `test_coordinator.py`, `test_setup_unload.py`, `test_device_trigger.py`, `test_diagnostics.py`. Changelog and HA-free tests run on Windows and Linux.

All other tests still run on a Windows host. A green native Windows `pytest` is **not** the same as CI if you changed config flow, coordinator, setup/unload, device triggers, or diagnostics.

**Full suite on a Windows machine:** run [`scripts/test.ps1`](../../scripts/test.ps1). It builds [`docker/test.Dockerfile`](../../docker/test.Dockerfile) (Debian, Python 3.13 — same as CI) and runs pytest inside it, where `fcntl` works and nothing is skipped. Extra arguments are passed through: `./scripts/test.ps1 tests/test_coordinator.py -v`. The dependency layer is cached, so only the first build is slow. Do not detect Docker from Windows `conftest` — if pytest is already in Linux, the skip does not apply.

Do **not** base that image on `ghcr.io/home-assistant/home-assistant`: it is Alpine/musl and resolves wheels through Home Assistant's `musllinux-index`, which fails TLS verification on networks that inspect certificates. `python:3.13-slim` also fails — `lru-dict` builds from source and needs `gcc`.

## What to test where

Prefer HA-free unit tests for REST / SignalR / store. Use the HA plugin (`hass`, `MockConfigEntry`) for config flow, coordinator, and setup/unload.

| Change                                                              | Extend or add                                                                                                                                                  |
| ------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Manifest version bump                                               | `test_changelog_release.py` — changelog must have a matching `## [x.y.z]` section                                                                              |
| New HA-free module (Phase B)                                        | `_HA_FREE_MODULES` in `test_ha_free_imports.py`                                                                                                                |
| UI strings / locales (when locales grow)                            | `test_translations.py`                                                                                                                                         |
| REST / SignalR / store                                              | HA-free tests next to those modules                                                                                                                            |
| Config flow, coordinator, load/unload, device triggers, diagnostics | `test_config_flow.py`, `test_coordinator.py`, `test_setup_unload.py`, `test_device_trigger.py`, `test_diagnostics.py` (full suite: CI / WSL / Linux container) |
| Catalog / platform semantics (Phase B)                              | entity / platform tests when platforms exist                                                                                                                   |

Do not copy Carlinko changelog assertions (WebSocket / vehicle bullets) into Traffical tests.

## When a test is required

- New behavior: add or extend a test unless the change is docs-only.
- Bug fix: add or extend a test that would have failed before the fix, when that is practical.
- Do not skip tests to land a change. Do not add a job-wide coverage number.

Pytest config lives in [`pyproject.toml`](../../pyproject.toml) (`[tool.pytest.ini_options]`).
