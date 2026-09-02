---
name: fix-bug
description: >-
  Fixes a Traffical integration or engine bug with reproduce, correct layer,
  regression test, and honest notes. Use when fixing a bug, regression,
  incorrect entity value, failed check-in, config flow error, or HTTP/SignalR
  failure.
---

# Fix a bug

Read before editing:

- [docs/standards/coding.md](../../../docs/standards/coding.md)
- [docs/standards/testing.md](../../../docs/standards/testing.md)
- [docs/standards/ci.md](../../../docs/standards/ci.md)

## Checklist

1. **Reproduce**: Home Assistant with `custom_components.traffical: debug`, and/or `python engine/entrypoint.py` from the repo root. Redact tokens, OTP, phone, child names, and GPS from logs.
2. **Locate the layer**: models vs API/SignalR vs coordinator/config flow vs platform. Do not patch the wrong side of the HA-free boundary (see coding.md current vs target).
3. **Regression test first** when practical (a test that fails on current main, then the fix). Follow testing.md for which file to extend.
4. **Same rules as features**: if English strings were added or changed, follow [translate-locales](../translate-locales/SKILL.md). No `homeassistant` in HA-free modules; [docs/logging.md](../../../docs/logging.md) if logs change.
5. **Honesty**: do not silently invent API fields. State confirmed vs inferred and tenant / customer-type in the PR.
6. **Version and changelog**: follow [changelog-version](../changelog-version/SKILL.md) (`### Fixed`).
7. **Before PR:** from repo root, `pre-commit run --all-files`. If it fails, fix the reported issues (including files the hooks auto-format) and run again until it is clean. Do not skip hooks. Then `pytest` (full suite in Linux if HA plugin tests changed — [testing.md](../../../docs/standards/testing.md)).
8. **PR**: focused fix, test plan, [bug report context](../../../.github/ISSUE_TEMPLATE/bug_report.md) if useful. Do not drop required CI jobs.
