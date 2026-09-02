# Coding standards

How we write Python in this repo. Product rules (passenger/parent, OTP, translations) live in [CONTRIBUTING.md](../../CONTRIBUTING.md) and the Cursor skills under `.cursor/skills/`. Tests and CI: [testing.md](testing.md), [ci.md](ci.md). Domain design: [home-assistant-integration.md](../home-assistant-integration.md), [api-reference.md](../api-reference.md).

Formatting is [pre-commit](../../.pre-commit-config.yaml) (Black, isort, flake8, pyupgrade `--py39-plus`, bandit on `custom_components/`, prettier). Run `pre-commit run --all-files`. Do not hand-format against a different style.

CI runs Python **3.13**. Black/pyupgrade still target **3.9+**. Runtime deps: [`requirements.txt`](../../requirements.txt). Test/hook deps: [`requirements-dev.txt`](../../requirements-dev.txt).

## Current vs target

|         | **Today (Phase A)**                                 | **Target (Phase B)**                                                                                |
| ------- | --------------------------------------------------- | --------------------------------------------------------------------------------------------------- |
| Product | Stub HA integration + fat CLI                       | Native HA is the product                                                                            |
| Clients | `engine/` (`requests`, `signalrcore`)               | HA-free modules under `custom_components/traffical/managers/`                                       |
| Engine  | Many Python files (`entrypoint.py`, clients, store) | `engine/entrypoint.py` (+ HA-free path mount) only                                                  |
| HTTP    | `requests` / `signalrcore` in `engine/`             | Long-term: `aiohttp` like other HA integrations; keep current stack until SignalR-on-aiohttp exists |

Until Phase B, **do not** reformat or relocate `engine/` clients. Pre-commit excludes `engine/` from Black/flake8/isort/pyupgrade/autoflake. Do not add a second copy of those clients under `custom_components/`.

## Directory structure

Two roots. Do not flatten `common/`, `managers/`, `models/`, or `translations/` onto the **project** root.

**Project root** (repo):

| Folder                         | Put here                                           | Do not put here                         |
| ------------------------------ | -------------------------------------------------- | --------------------------------------- |
| `custom_components/traffical/` | The Home Assistant integration package (see below) | —                                       |
| `engine/`                      | CLI (today: full clients; target: harness only)    | A second copy of clients after Phase B  |
| `tests/`                       | pytest                                             | Runtime code                            |
| `docs/`                        | Standards and domain docs                          | Code                                    |
| `scripts/`                     | One-off generators                                 | Imports from the integration at runtime |

**Package root** (`custom_components/traffical/`):

| Folder / files     | Put here                                                                                                                                               | Do not put here                                   |
| ------------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------ | ------------------------------------------------- |
| Package root files | HA entry: `__init__.py`, `config_flow.py`, `diagnostics.py`, `manifest.json`, `services.py` / `services.yaml`, `strings.json`, one module per platform | Vendor HTTP, ride decode                          |
| `common/`          | Constants, pure helpers, HA entity base/setup shared by platforms                                                                                      | Vendor HTTP, per-platform entity classes          |
| `managers/`        | Long-lived I/O and orchestration: HTTP, SignalR, persistence, HA coordinator                                                                           | Payload-only shapes                               |
| `models/`          | Data shapes, ride/station/check-in — no I/O                                                                                                            | `aiohttp` / `requests`, config entries, platforms |
| `translations/`    | HA locale JSON (`en.json`, …)                                                                                                                          | Python                                            |

**Fit (target):** network I/O → package `managers/`; typed facts about payloads/state → package `models/`; shared and not I/O → package `common/`; HA platform registration → thin `*.py` next to those folders. Native Home Assistant is the product; the engine only mounts the same package.

**HA-free (target):** `models/`, mobile/identity/SignalR clients, `managers/store.py`, and `common/consts.py` must not import `homeassistant`. Coordinator, platforms, config flow, and HA-facing `common/` may. When those modules exist, enforce with `tests/test_ha_free_imports.py` — extend `_HA_FREE_MODULES` when you add another HA-free module.

## File shape

**Class is the default** for domain and I/O files: one primary class per module. Small functions in the same file are fine when they do not need `self` (e.g. `async_setup_entry` next to the entity class).

Do not invent a helpers class of only `@staticmethod`s.

| Kind                                                                       | Shape                                                         |
| -------------------------------------------------------------------------- | ------------------------------------------------------------- |
| Managers, models, config/options flows, platforms, `common/base_entity.py` | **Class file**                                                |
| `common/consts.py`, `common/helpers.py`                                    | **Functions / constants / enums only**                        |
| HA glue: `__init__.py`, `diagnostics.py`, `services.py`                    | **Function files** — that is Home Assistant’s API             |
| Common factories: `entity_setup.py`, `entity_descriptions.py`              | **Function files** — spec → entities / `EntityDescription`    |
| Engine `entrypoint.py` (target)                                            | Functions and `async def main` — no extra engine Python files |

**Platforms:** `async_setup_entry` plus **one** entity class; no second entity type in that file.

**`common/` is mixed:** `base_entity.py` is a class; consts/helpers and factories are functions. Do not turn `__init__.py`, diagnostics, or services into classes.

## Imports

1. Module docstring.
2. `from __future__ import annotations`
3. **Stdlib**, then **third party**, then **first party** (isort, Black profile). `homeassistant` and `tests` are first-party in [`pyproject.toml`](../../pyproject.toml).
4. Inside the integration package, use **relative** imports (`.common`, `..models`). After Phase B, the engine uses **absolute** `traffical.*` after the HA-free path mount.
5. Then `_LOGGER` / module constants, then code.

**Always import at the top of the file.** Never import inside a function, method, or class body.

**Never use conditional imports:** no `if …: import`, no `try/except ImportError` around imports, no `if TYPE_CHECKING:` import blocks. If a cycle appears, split modules rather than hiding the import.

**Exception:** [`tests/conftest.py`](../../tests/conftest.py) may `try: import fcntl` so Windows can skip the HA pytest plugin. No other file gets this exception.

## Strings

- Use **f-strings** for values, paths, exceptions, and log messages (`f"invalid phone={phone!r}"`). Do not use `'{}'.format()` or `%` interpolation for ordinary Python strings.
- Prefer `key=value` fragments over prose. Use `!r` for raw or invalid input.
- User-visible UI copy belongs in `strings.json` / translations, not concatenated English in Python.

New engine log lines should use f-strings as well (some older CLI lines still use `%s`).

## Logging

Shared contract for integration and engine. Named HA lines, flows, and `caplog` examples: [logging.md](../logging.md).

**Who logs.** `_LOGGER = logging.getLogger(__name__)`. No `print` in library code. Do not invent extra logger names. `models/` do not log (decode is silent). Thin platforms (`sensor.py`, …) do not log; add a logger only if the module owns a user-visible action. `services.py` may DEBUG register/unregister.

**Who configures.** Only Home Assistant (integration) and `engine/entrypoint.py` (harness) attach handlers or set the root level. Managers and models never call `basicConfig`, never add handlers. The integration registers the parent logger in `manifest.json` (`custom_components.traffical`); child `__name__` loggers inherit — do not add extra `loggers` entries.

**Levels.** DEBUG = path/attempt; INFO = outcome/milestone; WARNING = expected failure; ERROR / `exception` = cannot continue / unexpected. Do not log the same fact at INFO and DEBUG. The layer that owns the result logs it; callers do not repeat it.

**Exceptions.** Unexpected failure in `except`: `_LOGGER.exception("…")` (traceback). Do not also paste `error={err}` into that message. Recoverable fallback: `_LOGGER.debug("…", exc_info=True)` so INFO stays clean.

**Message shape.** Stable grep-friendly prefixes (`login ok`, `auth failure source=`). `key=value` fragments. Tests assert those substrings, so do not churn them. HTTP/SignalR DEBUG is method + path or connect attempt — not bodies, tokens, OTP, or GPS payloads at INFO.

**Redaction.** Never log OTP codes, tokens, full request/response bodies, full phone numbers, child names, or GPS coordinates at INFO. Use `partial_id` / masking helpers when they exist.

**Home Assistant:** do not attach handlers. HA sets the level for `custom_components.traffical`.

**Engine:** may configure logging in `entrypoint.py` (stdout, `TRAFFICAL_LOG_LEVEL` / `DEBUG=true`). Default INFO. Same client loggers, not a parallel `print` protocol.

## HTTP and realtime

**Current (engine):** `requests` and `signalrcore`. Explicit timeouts. Session/store owned by the CLI.

**Target:** one stack (`aiohttp`) when a working SignalR path exists. Own the session at the coordinator or engine boundary; pass it into clients. `python-dotenv` is engine-only. Integration credentials come from the config entry.

## Safety

Never commit, screenshot, or paste `.env`, `config.json`, tokens, API keys, OTP codes, full phone numbers, child names, or live GPS traces.
