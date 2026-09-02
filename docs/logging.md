# Logging standard (Traffical integration)

Guidance for **developers** adding or changing logs in `custom_components/traffical/` and (today) `engine/`.
Operators tuning Home Assistant should use the [README troubleshooting](../README.md#troubleshooting)
section; this doc defines **levels**, **message shape**, and **layering** so logs stay
readable at `info` and actionable at `warning`.

Logger parent: `custom_components.traffical`. Engine CLI may use `LOG_LEVEL` (process env or repo-root `.env`).

## Safety

- Never log OTP codes, passwords, refresh/access tokens, or full API / SignalR response bodies.
- Never log full phone numbers, child names, or GPS coordinates at **INFO**.
- Redact identifiers: `partial_id()` for entry IDs and ride/route ids in user-visible lines; mask phone on config-flow submit lines.
- Vendor login failures may include a **code** and **msg** from the API if already sanitized.

## INFO vs DEBUG

They are not two verbosity settings for the same fact.

|          | **INFO**                                                                   | **DEBUG**                                                                |
| -------- | -------------------------------------------------------------------------- | ------------------------------------------------------------------------ |
| Answers  | What happened that matters for this flow?                                  | How did the code get there?                                              |
| Examples | `config flow created entry`, `setup entry`, `login ok`, ride status change | OTP request attempt, `POST /api/Mobile/Rides/…`, SignalR connect attempt |
| Avoid    | Internal call chains, HTTP method paths, per-platform reconcile spam       | User-visible milestones or failures only at DEBUG                        |

GPS lat/lng, station lists, and child display names belong at **DEBUG** (or not at all), not INFO.

**Pairing:** DEBUG (path/attempt) → INFO or WARNING (outcome).

```text
DEBUG    _validate_login → IdentityClient.request_otp
INFO     otp requested
```

```text
DEBUG    _validate_login → IdentityClient.verify_otp
WARNING  login failed code=…
WARNING  config flow failed step=user error=invalid_auth …
```

**Wrong:** auth or config errors at DEBUG only; successes or failures duplicated at both INFO and DEBUG for the same fact.

Between two INFO milestones in a flow, there should be enough DEBUG to trace the path when `custom_components.traffical: debug` is enabled.

## Levels

| Level         | Use for                                                                                                                                                    |
| ------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **debug**     | Call chain, retries, HTTP paths, SignalR frames, entity key lists, GPS points                                                                              |
| **info**      | Milestones and results: flow start or success, setup/reload/unload, `login ok`, coordinator start/stop, ride became Ongoing / Finished, platforms complete |
| **warning**   | Expected failures the operator can fix or tolerate: bad OTP, stale token (before reauth), rate limit, SignalR setup timeout                                |
| **error**     | Integration cannot continue without user action: `starting reauth flow`, setup auth failed                                                                 |
| **exception** | Unexpected bugs (`exc_info=True`): uncaught setup failure, listener crash, store save failure                                                              |

## Config and options flows

- User-facing validation failures → **warning** at `config_flow` (with `step=…` and `error=…`) and vendor detail at the identity/mobile client where applicable.
- Flow boundaries (started, submit, created entry, success reload, abort) → **info**.
- Unexpected exceptions in a flow step → **exception** if truly unknown; handled cases → **warning** with context.

Phase A stub flow only logged start and created entry. The live flow logs OTP request and login outcome (never the code).

## Lifecycle (`__init__.py`)

- **info:** `setup entry`, `unload entry`, `unload platforms ok=…`, `reload entry … reason=update_listener`, `platforms setup complete count=N`
- **error:** `setup auth failed entry_id=…` on `ConfigEntryAuthFailed`
- **debug:** unload/reload/setup sub-steps

Use `(existing entry)` on setup when `entry.runtime_data` is already set (reload/boot after first load).

## Coordinator (Phase B)

- **info:** `coordinator starting` / `coordinator stopping`, ride list refreshed count, SignalR connected/disconnected for a live ride
- **debug:** poll interval, HTTP paths, `Monitor(rideId)` invoke, coordinate frames (counts, not lat/lng at INFO)
- **warning:** auth failure, poll failed, SignalR timeout
- **error:** `starting reauth flow entry_id=…`

One INFO summary per poll tick that changed ride membership; per-platform entity reconcile → **debug**.

## API and SignalR

- **info:** `login ok`, `otp requested`, ride status milestone (`status=Ongoing`), SignalR `connected` / `disconnected`
- **debug:** `POST /api/Mobile/Rides/…`, check-in statuses, monitoring path GET, hub invoke, frame counts
- **warning:** `login failed`, HTTP non-OK, hub connect failed

Last HTTP snapshots for **diagnostics** are RAM-only (`query_log_for_diagnostics`). They are not log lines. Do not INFO-dump them. GPS, OTP, and tokens stay out of the diagnostics file.

## Message style

- Prefer stable, grep-friendly prefixes: `config flow failed step=user`, `auth failure source=http`.
- Use `partial_id()` for IDs in messages.
- Avoid triple-logging the same auth failure (flow + client once each is enough).

## Logger modules

| Logger                                             | Module                     |
| -------------------------------------------------- | -------------------------- |
| `custom_components.traffical`                      | `__init__.py`              |
| `custom_components.traffical.config_flow`          | `config_flow.py`           |
| `custom_components.traffical.managers.coordinator` | `coordinator.py` (Phase B) |
| `custom_components.traffical.managers.store`       | `store.py` (Phase B)       |

HA registers the parent logger in `manifest.json` (`loggers`: `custom_components.traffical`). Engine modules today log under `engine.*` until they move into the package.

## Testing log changes

- Use `caplog` in pytest; assert **warning** for operator-visible failures, not DEBUG-only.
- After changes, spot-check mentally at three HA levels:
  - **`info`:** milestones only — add integration or boot should tell a short story.
  - **`warning`:** failures visible without success noise.
  - **`debug`:** path between INFO lines is reconstructible.

Example operator config:

```yaml
logger:
  logs:
    custom_components.traffical: info # default recommendation
    # custom_components.traffical: debug   # development / support
    # custom_components.traffical: warning # problems-only tail
```

## Operational flows (where to log)

When touching code, know which flow you are in:

1. Add account — `config_flow` + first `async_setup_entry` (OTP in Phase B)
2. Lifecycle — setup, reload, unload, remove, options, reauth
3. HTTP poll — rides / check-in / details
4. Auto SignalR — connect when Ongoing, disconnect when finished
5. Local entity action — refresh button, child select

New logs should fit the level rules for that flow without duplicating another layer’s outcome.
