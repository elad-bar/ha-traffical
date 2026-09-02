# Contributing

Thanks for taking a look. Contributions — especially from people with **other
Traffical tenants, customer types, or passenger accounts** — are very welcome.

By participating, you agree to follow the [Code of Conduct](CODE_OF_CONDUCT.md). Pull requests
get a [template](.github/PULL_REQUEST_TEMPLATE.md); _which tenant / customer-type you validated_
and _confirmed vs inferred_ matter most, because wrong ride state silently lies to a parent.

## Good first contributions

- **Tenant / customer-type report.** Run `python engine/entrypoint.py` and open a
  [tenant report](https://github.com/elad-bar/ha-traffical/issues/new?template=tenant_report.md).
- **Docs** — setup friction, passenger flow notes, HA entity notes.
- **Translations** — polish UI strings for your language (see below).

## Translations

UI strings are in [`custom_components/traffical/strings.json`](custom_components/traffical/strings.json)
(English source) and [`custom_components/traffical/translations/`](custom_components/traffical/translations/)
(one JSON file per HA locale). Shipped locales: English (`en`) and Hebrew (`he`). Brand **Traffical** stays untranslated.

When you add or change copy in `strings.json` / `translations/en.json`, or you add a locale, follow the Cursor skill [`.cursor/skills/translate-locales/`](.cursor/skills/translate-locales/). When translation tests exist, run `pytest tests/test_translations.py`.

**Prefer editing locale JSON directly** (or a focused PR) when improving wording.
Do not commit API keys.

## Before you start

- Skim **[README.md](README.md)**, **[docs/home-assistant-integration.md](docs/home-assistant-integration.md)**, **[docs/api-reference.md](docs/api-reference.md)**, and **[docs/logging.md](docs/logging.md)** when adding logs or debugging flows.
- Run: `python engine/entrypoint.py` from the repo root (OTP login CLI).
- Install hooks once: `pip install -r requirements-dev.txt && pre-commit install`.
  Hooks run on commit (black, flake8, isort, bandit, yamllint, prettier, etc.).
  To run everything against the tree: `pre-commit run --all-files`.
  Pull requests also run [CI](.github/workflows/ci.yml) (pre-commit, hassfest, HACS, pytest).

## Standards

Project invariants (layers, HA-free boundary, tests, CI jobs) live in:

- [docs/standards/coding.md](docs/standards/coding.md)
- [docs/standards/testing.md](docs/standards/testing.md)
- [docs/standards/ci.md](docs/standards/ci.md)

Cursor skills for adding a feature, fixing a bug, changelog/version, and translations are under [`.cursor/skills/`](.cursor/skills/).

## Releases

Version lives in [`custom_components/traffical/manifest.json`](custom_components/traffical/manifest.json).
When merging to `main` / `master`, CI runs the same checks, then (on success) creates `v<version>`
if that tag is missing and publishes a [GitHub Release](https://docs.github.com/en/repositories/releasing-projects-on-github)
whose notes come from the matching section in [`CHANGELOG.md`](CHANGELOG.md). Release title is `Traffical v…`.

Before bumping the manifest for a release (agents: [changelog-version skill](.cursor/skills/changelog-version/SKILL.md)):

1. Compare `manifest.json` `version` to the latest **GitHub release**. If they match, increment the **patch** and add a new `## [x.y.z] - YYYY-MM-DD` section. If the manifest is already ahead, only append changelog bullets.
2. Document the change in [`CHANGELOG.md`](CHANGELOG.md) (Keep a Changelog: Added / Changed / Fixed).
3. Run `pytest tests/test_changelog_release.py` — it fails if the manifest version has no changelog entry.

## Pull requests

1. Keep changes focused — one feature/fix per PR.
2. Runtime pip deps live in [`requirements.txt`](requirements.txt)
   (`aiohttp`, `homeassistant` for local typing / IDE).
   HA-free code under `custom_components/traffical/models/` and the API/SignalR clients in
   `managers/` must stay free of `homeassistant` imports. Test-only deps (including
   `pre-commit`) are in `requirements-dev.txt`.
3. **Never** include `.env`, `config.json`, tokens, API keys, OTP codes, full phone numbers,
   child names, or GPS traces in a commit, screenshot, or log paste.
4. If you touch ride/check-in behaviour, say which tenant / customer-type you validated against.

## Ground rules

- Be honest about accuracy. Mark assumptions as assumptions.
- This is for accessing _your own_ passenger/parent account. Don't attack Traffical
  infrastructure, scrape other users' data, or abuse the API at scale.

Questions? Open a [Discussion](https://github.com/elad-bar/ha-traffical/discussions).
