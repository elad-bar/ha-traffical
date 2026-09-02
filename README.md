# Traffical

Home Assistant custom integration for **Traffical** school-shuttle rides (passenger / parent).
One config entry is one identity (phone + OTP). The integration is a companion for today’s
rides, check-in, and live bus position — not a dispatcher, driver, or marketplace client.

Not affiliated with Traffical / Shift.

Product design: [docs/home-assistant-integration.md](docs/home-assistant-integration.md).
API notes: [docs/api-reference.md](docs/api-reference.md).
Passenger flow: [docs/passenger-experience.md](docs/passenger-experience.md).

**Status:** Phase A ships a **stub** (config flow placeholder, no OTP yet) so HACS / hassfest /
CI can run. The working login CLI remains `python engine/entrypoint.py`. Real HA platforms land
in a later release.

## Prerequisites

- Home Assistant (see `hacs.json` for the tested version)
- A Traffical passenger or parent account
- Network access from Home Assistant to Traffical cloud services (when the stub is replaced)

## Install

### HACS (recommended)

1. HACS → Integrations → ⋮ → Custom repositories.
   Add this repo as type **Integration** (until it is listed in HACS).
2. Install **Traffical**, then restart Home Assistant.
3. Settings → Devices & services → Add integration → **Traffical**.

### Manual

Copy `custom_components/traffical/` into
`<config>/custom_components/traffical/`, restart, then add the integration.

## Configuration

Phase A: the config flow is a placeholder and does not request phone or OTP.

Target (Phase B): one entry per account; stored refresh token; hub device plus a child device
per recurring ride (`routeId` + `direction`).

## Engine CLI

From the repo root (session in `data/config.json`):

```bash
python engine/entrypoint.py
python engine/entrypoint.py --clean
python engine/entrypoint.py --env Live
```

Requires packages from [`requirements.txt`](requirements.txt).

## Languages

Config flow text follows **Settings → System → General → Language**.
Shipped UI translations live under
[`custom_components/traffical/translations/`](custom_components/traffical/translations/).
Phase A includes English only; other languages fall back to English.

Brand **Traffical** is not translated.

## Troubleshooting

```yaml
logger:
  logs:
    custom_components.traffical: info
    # custom_components.traffical: debug
```

Do not paste tokens, OTP codes, full phone numbers, child names, or GPS traces in issues.

Developer logging contract: [docs/logging.md](docs/logging.md).

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) and [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md).
Standards: [docs/standards/coding.md](docs/standards/coding.md).
