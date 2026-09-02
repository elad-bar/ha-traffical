# Traffical engine (CLI)

Home Assistant is the product. This folder is a thin asyncio CLI that mounts the same HA-free package used by the integration.

| Path                                           | Role                                                                     |
| ---------------------------------------------- | ------------------------------------------------------------------------ |
| `engine/ha_free_path.py`                       | Synthetic `traffical` package pointing at `custom_components/traffical/` |
| `engine/entrypoint.py`                         | Login menu, day’s rides, auto SignalR                                    |
| `custom_components/traffical/managers/`        | Identity, mobile REST, SignalR, store                                    |
| `custom_components/traffical/models/`          | Ride/station helpers                                                     |
| `custom_components/traffical/common/consts.py` | HA-free constants                                                        |

```text
python engine/entrypoint.py
python engine/entrypoint.py --clean
python engine/entrypoint.py --env Live
```

Session file: `data/config.json` (repo root). Do not commit it.

Optional logging: a repo-root `.env` is loaded at startup. `LOG_LEVEL` (a level name such as `DEBUG` or `INFO`, default `INFO`) is the only variable. Variables already set in the process are not overwritten. Do not commit `.env`.

Install and env-var details: [README.md](../README.md#engine-cli).
