# Alignment with ha-carlinko — progress

Bring this repo to the same **custom-component concept** as [ha-carlinko](https://github.com/elad-bar/ha-carlinko): Home Assistant is the product; `engine/` is a thin CLI that mounts HA-free code under `custom_components/traffical/`.

Mark items `[x]` when done. Keep Phase A and Phase B as separate PRs.

**Naming:** domain `traffical`, display **Traffical**, logger `custom_components.traffical`, env `TRAFFICAL_LOG_LEVEL`. GitHub: `elad-bar/ha-traffical` (confirm before wiring issue/docs URLs).

**Keep as-is:** `docs/product-overview.md`, `docs/api-reference.md`, `docs/passenger-experience.md`, `docs/home-assistant-integration.md`. Do not copy Carlinko vehicle docs (`api-map.md`, `api-contracts.md`, `control-opcodes.md`) or Carlinko platform/blob Python.

---

## Phase A — Scaffolding

Tooling, standards, skills, folders, and a **stub** integration so CI can run. Do **not** move engine clients or rewrite HTTP/SignalR.

### A1. Standards and skills

- [x] Add `docs/standards/coding.md` (layers, HA-free boundary, `custom_components/traffical/`). Note **current vs target** for `engine/` and `requests` / `signalrcore`.
- [x] Add `docs/standards/testing.md` (pytest from repo root, Windows/`fcntl` skips, intended test map).
- [x] Add `docs/standards/ci.md` (jobs, release from manifest + CHANGELOG).
- [x] Add `docs/logging.md` adapted from Carlinko (levels, redaction: OTP, tokens, phone, child names, GPS at INFO).
- [x] Add `.cursor/skills/add-feature/SKILL.md` (Traffical docs; no opcodes / VIN / car-region).
- [x] Add `.cursor/skills/fix-bug/SKILL.md` (logger `custom_components.traffical`).
- [x] Add `.cursor/skills/translate-locales/SKILL.md` (paths under `custom_components/traffical/`; brand **Traffical** untranslated).
- [x] Add `.cursor/skills/changelog-version/SKILL.md` (`custom_components/traffical/manifest.json`).
- [x] Add `CONTRIBUTING.md` (passenger/parent, OTP, translations, standards links — not Carlinko cars).

### A2. Folders

- [x] `custom_components/traffical/common/` (`__init__.py`)
- [x] `custom_components/traffical/managers/` (`__init__.py`)
- [x] `custom_components/traffical/models/` (`__init__.py`)
- [x] `custom_components/traffical/translations/`
- [x] `tests/` (`__init__.py`)
- [x] `scripts/`
- [x] `.github/workflows/`
- [x] `.github/ISSUE_TEMPLATE/`
- [x] `.cursor/skills/` (four skill dirs above)

### A3. Stub integration (required for hassfest / HACS)

- [x] `manifest.json` — `domain: traffical`, `config_flow: true`, `iot_class: cloud_polling`, docs/issues URLs, `loggers: ["custom_components.traffical"]`, version `0.1.0`
- [x] `__init__.py` — setup / unload stub
- [x] `config_flow.py` — user-step placeholder
- [x] `strings.json` + `translations/en.json`
- [x] `quality_scale.yaml` (parity with Carlinko, optional but useful)
- [x] `CHANGELOG.md` with `## [0.1.0]` (Keep a Changelog)
- [x] `hacs.json` — `"name": "Traffical"`
- [x] Do **not** copy Carlinko `sensor.py` / `lock.py` / blob models

### A4. CI, pre-commit, repo config

- [x] `.github/workflows/ci.yml` — pre-commit, hassfest, HACS, pytest, release; paths `custom_components/traffical/manifest.json`; title `Traffical v…`
- [x] `.pre-commit-config.yaml` — **exclude `engine/`** from Black/flake8 until Phase B
- [x] `pyproject.toml` (Black, isort, pytest)
- [x] `setup.cfg` (flake8)
- [x] `bandit.yaml`
- [x] `.yamllint`
- [x] `.prettierignore`
- [x] `requirements-dev.txt` (`pre-commit`, pytest, `pytest-homeassistant-custom-component`, `deep-translator` if translation scripts land)
- [x] `scripts/extract_changelog_section.py`
- [x] `.github/CODEOWNERS` — `custom_components/traffical/ @elad-bar`
- [x] `CODE_OF_CONDUCT.md` (passenger / child / location privacy, not VIN)
- [x] `LICENSE` (same as Carlinko if desired)
- [x] GitHub PR template; bug / feature issue templates; replace car compatibility with tenant / customer-type; `config.yml` discussions URL
- [x] `.vscode/settings.json` — `extraPaths` only; **no** machine-specific interpreter. Stop ignoring `.vscode/` in `.gitignore` if committed.
- [x] Merge `.gitignore`: keep `/app/`, `/data/`, `/debug/`; add `.env`; drop `.vscode/` ignore if committing settings
- [x] `README.md` — Traffical HACS / install (repo has none today)
- [x] `requirements.txt` — keep engine deps (`requests`, `signalrcore`); add `homeassistant` for IDE/CI if matching Carlinko

### A5. Tests that can pass on a stub

- [x] `tests/conftest.py` — load HA plugin on Unix; skip HA-runtime modules on Windows (`fcntl`)
- [x] `tests/test_changelog_release.py` — Traffical `manifest.json` path; no Carlinko changelog assertions
- [x] Translation tests only if `strings.json` / locales exist and are worth locking

### A6. Phase A done when

- [x] `pre-commit run --all-files` is clean (engine excluded or not yet formatted)
- [x] CI jobs exist and the stub passes hassfest, HACS, pytest
- [x] Existing `engine/` still runs as today (`python engine/entrypoint.py`)

---

## Phase B — Same architecture

Move runtime into the integration package. Native HA is the product; engine only mounts HA-free modules.

Product target: [home-assistant-integration.md](./home-assistant-integration.md) (one entry = one identity; hub + child devices per recurring ride; HTTP coordinator + auto SignalR).

### B1. Relocate engine into the package

| Today (`engine/`)                | Target                                                 |
| -------------------------------- | ------------------------------------------------------ |
| Identity / OTP                   | `managers/`                                            |
| Mobile REST                      | `managers/` (API / mobile client)                      |
| SignalR                          | `managers/`                                            |
| Session store                    | `managers/store.py`                                    |
| Ride / station / check-in shapes | `models/`                                              |
| Shared consts (HA-free)          | `common/consts.py`                                     |
| CLI                              | `engine/entrypoint.py` + `engine/ha_free_path.py` only |

- [ ] Move clients/store/models out of `engine/` into `custom_components/traffical/`
- [ ] Shrink `engine/` to entrypoint + synthetic `traffical` package mount (Carlinko `ha_free_path.py` pattern)
- [ ] `tests/test_ha_free_imports.py` — `_HA_FREE_MODULES` for Traffical
- [ ] Update `engine/README.md` (layout table)
- [ ] Drop the Phase A pre-commit exclude for `engine/` once it is thin

### B2. HTTP / realtime stack

- [ ] Choose the HTTP / SignalR stack: target is `aiohttp` REST + an **async** hub client we own (thin negotiate + `ws_connect`, or a Core SignalR library proven on Live). HA has no SignalR SDK. `signalrcore` + executor is a spike only, not the long-term stack. Details: [coding.md](./standards/coding.md)
- [ ] Timeouts explicit; session owned at coordinator / engine boundary
- [ ] `python-dotenv` engine-only; HA credentials from the config entry
- [ ] Update `requirements.txt` to match the chosen stack
- [ ] Update `docs/standards/coding.md` to remove the “engine still uses requests” exception when true

### B3. Home Assistant integration (real, not stub)

- [ ] Config flow: phone + OTP, stored refresh token
- [ ] Coordinator: poll rides / check-in / details on interval; faster near ride start
- [ ] Auto SignalR when ride is `Ongoing` / `OngoingMonitored`; disconnect on finished
- [ ] Devices: account hub + child per `routeId` + `direction` (not per daily `rideId`)
- [ ] Platforms (thin): `sensor`, `binary_sensor`, `button`, `select`, `device_tracker` as in the HA design
- [ ] Diagnostics (redacted)
- [ ] Services only if the design needs them (`services.py` / `services.yaml`)
- [ ] Options flow if poll interval / child select needs it

### B4. Tests and translations

- [ ] HA-runtime: `test_config_flow.py`, `test_coordinator.py`, `test_setup_unload.py`
- [ ] HA-free: REST / SignalR / store / decode as modules land
- [ ] `test_translations.py`; generate/fix scripts retargeted to `traffical` when locales grow
- [ ] Windows skip list in `conftest.py` matches real HA-plugin test files
- [ ] Full suite green on Linux (CI); native Windows pytest still skips HA plugin tests

### B5. Phase B done when

- [ ] Engine CLI uses the same package as HA (no duplicated clients)
- [ ] Integration matches [home-assistant-integration.md](./home-assistant-integration.md) v1 scope
- [ ] Skills / standards no longer describe a stub or a fat engine
- [ ] CI release path: bump `manifest.json` + `CHANGELOG.md`, merge to `main`

---

## Out of scope (v1)

- Driver GPS upload, route builder, join/QR, marketplace, incidents
- Checking in _other_ passengers
- Copying Carlinko entity catalogs, opcodes, or vehicle blob decode
- Reformatting the whole existing `engine/` in Phase A (exclude it from hooks instead)

---

## Progress log

| Date       | Phase | Note                                                                       |
| ---------- | ----- | -------------------------------------------------------------------------- |
| 2026-09-02 | —     | Research complete; this checklist created. No scaffolding applied yet.     |
| 2026-09-02 | A     | Stub integration, CI, standards, skills. Engine clients unchanged.         |
| 2026-09-02 | B     | Docs: HA has no SignalR SDK; Phase B target is async hub client + aiohttp. |
