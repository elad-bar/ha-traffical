# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [0.1.0] - 2026-09-02

### Added

- Native Home Assistant integration: phone + OTP config flow, coordinator poll, auto SignalR live GPS, hub + ride devices
- Home Assistant custom-component scaffolding: stub integration (`traffical`), HACS metadata, CI, and changelog/release wiring
- Ride device triggers for status, start, finish, check-in, arrived station, and approaching stop (same as the `traffical_*` events)

### Changed

- Station `geo_location` markers show only for the live ride, otherwise the next unfinished ride today

### Removed

- Hub session binary sensor; session health stays internal (`session_ok` / reauth)
