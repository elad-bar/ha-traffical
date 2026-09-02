---
name: translate-locales
description: >-
  LLM-translates Home Assistant UI strings using product context. For a feature
  or bug, only keys added or changed in English. For a new language, every key.
  Use when strings.json or translations change, when adding a locale, or when
  the user asks to translate Traffical UI copy.
---

# Translate locales

English source: [`strings.json`](../../../custom_components/traffical/strings.json) and [`translations/en.json`](../../../custom_components/traffical/translations/en.json) — keep those two in lockstep. Other locales live next to `en.json` under `custom_components/traffical/translations/`.

Translate in this chat with **product context** (config step, entity, related strings). **Traffical** stays untranslated. Keep placeholders (`{error}`, …) and technical tokens unless the locale already has a convention.

Phase A ships English only. Do not add machine-translation generator scripts unless locales grow.

## Which keys

**Feature or bug:** if this change adds or edits English terms, translate **only those keys** into every existing non-English `translations/*.json`. New key → fill it. Changed English → replace that key in each locale. Leave all other keys untouched.

**New language:** add `translations/<ha-locale>.json` and translate **all** English keys into that file. Do not rewrite other locales except listing the new file. HA locale codes match existing names (`zh-Hans`, `he`, …).

Skip this skill if English strings did not change and you are not adding a locale.

## After

When `tests/test_translations.py` exists, run it. Native-speaker PRs can still improve phrasing later.
