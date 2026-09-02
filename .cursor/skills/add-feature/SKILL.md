---
name: add-feature
description: >-
  Implements a new Traffical integration feature in the correct layer (entity,
  REST/SignalR, service, options, or engine-only) with translations, tests,
  and PR metadata. Use when adding a feature, new entity, new service, options
  field, API/SignalR capability, or engine-only change.
---

# Add a feature

Read before editing:

- [docs/standards/coding.md](../../../docs/standards/coding.md)
- [docs/standards/testing.md](../../../docs/standards/testing.md)
- [docs/standards/ci.md](../../../docs/standards/ci.md)
- [docs/home-assistant-integration.md](../../../docs/home-assistant-integration.md)
- [docs/api-reference.md](../../../docs/api-reference.md)

## Checklist

1. **Classify**: entity / REST or SignalR / HA service / options / engine-only. SignalR protocol lives in the HA-free hub client (`managers/`); coordinator / HA glue owns connect-when-Ongoing and marshaling onto the event loop ([coding.md](../../../docs/standards/coding.md)).
2. **Place the code** in the matching layer. Platforms stay thin. Do not add engine Python besides `engine/entrypoint.py` and `engine/ha_free_path.py`. Do not import `homeassistant` in HA-free modules; extend `tests/test_ha_free_imports.py` if you add one.
3. **Entities / strings:** follow the HA design (account hub + child device per `routeId` + `direction`, not per daily `rideId`). Update `strings.json` and `translations/en.json` together. If English terms were added or changed, follow [translate-locales](../translate-locales/SKILL.md). Translation procedure: [CONTRIBUTING.md](../../../CONTRIBUTING.md).
4. **API**: [docs/api-reference.md](../../../docs/api-reference.md) and [docs/passenger-experience.md](../../../docs/passenger-experience.md). No opcodes, VIN, car-region, or vehicle blob decode.
5. **Logs**: follow [docs/logging.md](../../../docs/logging.md). No OTP, tokens, full phone, child names, or GPS at INFO.
6. **Tests**: add or extend per testing.md. New behavior is not docs-only.
7. **Version and changelog**: follow [changelog-version](../changelog-version/SKILL.md) (`### Added` or `### Changed`).
8. **Before PR:** from repo root, `pre-commit run --all-files`. If it fails, fix the reported issues (including files the hooks auto-format) and run again until it is clean. Do not skip hooks. Then `pytest` (full suite in Linux if HA plugin tests changed — [testing.md](../../../docs/standards/testing.md)).
9. **PR**: one feature. Fill tenant / customer-type and confirmed vs inferred. Keep CI jobs as they are.
