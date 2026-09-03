# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [0.1.4] - 2026-09-03

### Changed

- Ride device title is `Traffical {from address} - {to address}` (passenger pickup and drop-off), not the shared line name

### Fixed

- Rename entity ids restored from the registry (including after remove and re-add) onto the id-based scheme when the entity is added

## [0.1.3] - 2026-09-03

### Changed

- Home Assistant setup always uses Live hosts; environment is no longer a config-flow field
- Engine CLI always uses Live hosts (no `--env`); same hosts as Home Assistant

### Fixed

- Set `entity_id` from route, direction, and station ids; `_attr_suggested_object_id` was ignored so ids still used transliterated device names

## [0.1.2] - 2026-09-03

### Fixed

- Stop SignalR from retrying negotiate after the integration is removed (`RuntimeError: Session is closed`)

## [0.1.1] - 2026-09-03

### Changed

- Suggest entity object ids from route, direction, and station ids (`traffical_392681_120_status`) instead of transliterating Hebrew device and station names

### Fixed

- Rename `TrafficalEntity._context` so it no longer shadows Home Assistant `Entity._context` (entities failed to finish adding: `'EntityContext' object has no attribute 'origin_event'`)

## [0.1.0] - 2026-09-02

### Added

- Native Home Assistant integration: phone + OTP config flow with reauth, coordinator refresh, hub device per account, and a ride device per recurring line (`routeId` + `direction`)
- Live bus GPS over `MobileDashboardHub` (Azure SignalR negotiate redirect, `Monitor(rideId)`, `ReceiveCoordinates`, `ArrivedToStation`), attached while a ride is ongoing and detached when it finishes
- Always-on `mobileHub` stream: `UpdateRideStatus` drives ride-status transitions and live-GPS attach/detach, `RouteSuccessfulSave` triggers a debounced refresh of the affected day
- Station `geo_location` markers for today's path, shown for the live ride or the next unfinished ride today
- Debug-grade config-entry and device diagnostics: last HTTP status/shape, dual SignalR hub health, ride summaries, and entity registry (no GPS, OTP, or tokens)
- Ride device triggers for status, start, finish, check-in, arrived station, and approaching stop, matching the `traffical_*` events
- Check-in, check-out, and not-coming buttons gated by passenger policy and ride status
- Hebrew (`he`) Home Assistant UI translations for the config flow, entities, and device triggers
- Engine CLI (`engine/entrypoint.py`) sharing the integration's HA-free clients, with an optional repo-root `.env` for `LOG_LEVEL`; after login it dumps loaded rides once and listens for polls and SignalR (no ride menu)
- Ride lookahead: today is listed while trips remain, then at most four days forward until the next unfinished ride, which is then cached. The **Next ride** sensor can point at that later day, while each line device keeps today's finished `rideId` — and the map pins — until the date rolls
- HACS metadata including brand assets, CI (pre-commit, hassfest, HACS, pytest), and changelog-driven release wiring
