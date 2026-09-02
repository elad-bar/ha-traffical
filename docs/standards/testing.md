# Testing standards

Run `pytest` from the **repo root**. There is no coverage gate.

[CI](ci.md) (Ubuntu, Python 3.13) is the authority for the **full** suite, including Home Assistant plugin tests.

## Windows vs Linux

[`tests/conftest.py`](../../tests/conftest.py) loads `pytest_homeassistant_custom_component` only when `fcntl` exists. Native Windows Python does not; HA-runtime modules listed in `_HASS_TEST_FILES` are skipped.

**Phase A:** `_HASS_TEST_FILES` is empty. There are no config-flow / coordinator / setup-unload tests yet. Changelog tests run on Windows and Linux.

**Phase B (intended skip list)** when those files exist:

- `test_config_flow.py`
- `test_coordinator.py`
- `test_setup_unload.py`

All other tests still run on a Windows host. A green native Windows `pytest` is **not** the same as CI if you changed config flow, coordinator, or setup/unload.

**Full suite on a Windows machine:** run pytest in **Linux** — WSL2 or a Linux Docker container (Docker Engine). Inside that environment `fcntl` works and nothing is skipped. There is no checked-in image yet; any Python 3.13 Linux environment with `requirements.txt` + `requirements-dev.txt` is enough. Do not detect Docker from Windows `conftest` — if pytest is already in Linux, the skip does not apply.

## What to test where

Prefer HA-free unit tests for REST / SignalR / store. Use the HA plugin (`hass`, `MockConfigEntry`) for config flow, coordinator, and setup/unload.

| Change                                          | Extend or add                                                                                                 |
| ----------------------------------------------- | ------------------------------------------------------------------------------------------------------------- |
| Manifest version bump                           | `test_changelog_release.py` — changelog must have a matching `## [x.y.z]` section                             |
| New HA-free module (Phase B)                    | `_HA_FREE_MODULES` in `test_ha_free_imports.py`                                                               |
| UI strings / locales (when locales grow)        | `test_translations.py`                                                                                        |
| REST / SignalR / store (as modules land)        | HA-free tests next to those modules                                                                           |
| Config flow, coordinator, load/unload (Phase B) | `test_config_flow.py`, `test_coordinator.py`, `test_setup_unload.py` (full suite: CI / WSL / Linux container) |
| Catalog / platform semantics (Phase B)          | entity / platform tests when platforms exist                                                                  |

Do not copy Carlinko changelog assertions (WebSocket / vehicle bullets) into Traffical tests.

## When a test is required

- New behavior: add or extend a test unless the change is docs-only.
- Bug fix: add or extend a test that would have failed before the fix, when that is practical.
- Do not skip tests to land a change. Do not add a job-wide coverage number.

Pytest config lives in [`pyproject.toml`](../../pyproject.toml) (`[tool.pytest.ini_options]`).
