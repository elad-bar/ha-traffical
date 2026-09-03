# Traffical — Home Assistant custom integration

Design for a **passenger / parent** custom integration. It is a school-shuttle companion in Home Assistant: today’s rides, check-in, live bus position, and typed map markers for stations. It is **not** a dispatcher, driver, or marketplace client.

Related: [product-overview.md](./product-overview.md) · [passenger-experience.md](./passenger-experience.md) · [api-reference.md](./api-reference.md)

The Python engine in this repo (`engine/`) already covers login, ride list, details, check-in statuses, monitoring path, and SignalR live GPS. The integration should reuse that surface.

---

## Product intent

One Home Assistant config entry = one Traffical identity (phone + OTP, stored refresh token). That entry owns an **account hub device** plus a **child device per recurring ride**.

Typical day (from live Mashcal passenger data):

- Morning inbound: home stop → school (`FinishedMonitored` after the trip)
- Afternoon outbound: school (`isTarget`, start) → home stop (`New` until the trip runs)

The integration should make that visible on the map and in automations without the user starting or stopping GPS tracking.

Out of scope for v1: driver GPS upload, route builder, join/QR, marketplace, incidents, checking in *other* passengers.

Download diagnostics from Settings → Devices & services → Traffical → ⋮. The file is for classifying auth vs HTTP vs SignalR vs disabled entities. It must not include GPS, OTP, tokens, or child names.

---

## Runtime model

### Coordinator refresh (HTTP)

Every **N minutes** (about 2–5) for non-streamed data. Faster (30–60s) when
the next ride is within ~30 minutes of start.

Each tick:

1. `POST /api/Mobile/Rides/{customerType}` for **today** while any of today’s rides are unfinished. If today is finished (or empty), list the next calendar days **one at a time** until an unfinished ride is found, at most 4 days ahead. Cached future days are not listed again until they become today or a `RouteSuccessfulSave` overlaps them.
2. `POST /api/Mobile/CheckIn/GetStatuses` for those `rideId`s
3. Ride details when a ride is new or status changed

Each recurring line device is bound to **today’s** occurrence only. If today’s trip is finished, that device stays `Finished*` (same `rideId`) until the next calendar day — tomorrow’s instance is not written onto the device. The hub **Next ride** sensor uses the cached occurrence window (live, else the next unfinished ride found within four days).

Respect mobile API rate limits (`X-Rate-Limit-Limit: 1s`). Do not poll every second.

`button.traffical_refresh` only triggers this coordinator. It does not start GPS.

### Ride status and route changes (SignalR)

Keep a user-scoped `mobileHub` connection open for the config-entry session.
It requires no subscription invoke:

- `UpdateRideStatus` is a JSON string containing PascalCase `Id` and `Status`.
  Patch a ride already present in the occurrence cache, then attach or detach live
  GPS immediately when the **bound** (today) ride is live.
- `RouteSuccessfulSave` is a JSON string containing `ChangeDateFrom`,
  `ChangeDateTo`, and `RouteId`. If its range overlaps today through +4 days, debounce for about
  five seconds and refresh only the overlapping dates over HTTP.

Reconnect `mobileHub` after a drop, token refresh, or child switch. It replaces
the fast ride-list status poll; initial rides, check-in, details, and route-save
follow-ups remain HTTP.

### Automatic live tracking (SignalR)

No track / stop buttons or services. Same idea as engine auto-track:

- When a ride first becomes `Ongoing` or `OngoingMonitored`, connect `MobileDashboardHub`, invoke `Monitor(rideId)`, seed position from `GET /api/Mobile/RideMonitoringPath/Get` if points exist
- Stream `ReceiveCoordinates` into the bus `device_tracker` immediately (do not wait for the next HTTP poll)
- `ArrivedToStation` marks that station **passed**
- When status becomes `Finished` or `FinishedMonitored` (or the hub should follow a different live ride), disconnect

If two rides were live, one dashboard hub at a time is enough; attach to the live ride.

Home Assistant has no SignalR helper. The hub client is ours (HA-free `managers/`). Prefer async SignalR on the event loop (`aiohttp` session); if the client is still sync (`signalrcore`), marshal callbacks onto the loop before updating entities. Stack and constraints: [coding.md](./standards/coding.md).

---

## Devices

The config entry is not a device. Create HA devices with `DeviceInfo`: the account is the **hub**; each recurring ride is a **child** (`via_device` = hub identifiers). Same pattern as a bridge plus bulbs.

### Account hub

One device per config entry (e.g. “Traffical · הכפר הירוק”, or parent / child name). Identifier: userinfo `sub` or `phone` (stable).

Entities on the hub only:

- Child select
- Refresh button
- Next ride sensor

Session health is internal (`session_ok`): entities go unavailable and reauth starts when refresh fails. There is no session binary sensor.

### Ride devices (one per recurring ride)

A Traffical **`rideId` is a one-day instance**. Do **not** create a new HA device per `rideId` (the registry would grow every school day).

**Device identity** = customer + `routeId` + `direction` (the recurring line). Example from live data:

| Child device | Stable id | Today’s instance (state, not identity) |
|--------------|-----------|----------------------------------------|
| Morning inbound | `routeId` 392681, `direction` 120 | `rideId` 39306112 |
| Afternoon outbound | `routeId` 428988, `direction` 121 | `rideId` 38592351 |

Entity ids stay stable (`device_tracker.traffical_392681_120_bus`). The coordinator writes **today’s** `rideId`, ticket, times, and stations onto that device. A finished today occurrence is not replaced by the next day’s `New` instance until the calendar date rolls.

Friendly name is `Traffical {from address} - {to address}` once ride details have stations: pickup is the passenger stop (`your_station` address), drop-off is the station whose **name** matches `passengerDestinationName` (not `isTarget`). Until then, fall back to the Traffical line `name`, then `routeId:direction`. Two directions of the same line therefore get different titles. Entity ids stay `{routeId}_{direction}` and do not use this title.

Entities on each ride device:

- Status, check-in, driver, vehicle
- Check-in / check-out / not coming buttons
- Bus `device_tracker`
- Station `geo_location`s (shown only for the focus ride: live, else next unfinished today)

**No assignment today** (weekend, holiday, not coming, empty list): the ride device stays in the registry and goes **unavailable**. Do not delete and recreate it.

`{ride}` in entity ids below is `{routeId}_{direction}` (the suggested object id), not the daily `rideId` and not the Hebrew ride name. Stations are `geo_location.traffical_{ride}_stop_{stationId}`. Leftover ids from the transliterated-name scheme are renamed when the entity is added.

---

## User actions

These are **entities**, not required YAML services. Presses call the same APIs. Optional `traffical.*` services may wrap the same functions for automations.

### Buttons

| Entity | Device | API | Available when |
|--------|--------|-----|----------------|
| `button.traffical_refresh` | Hub | Coordinator refresh | Session valid |
| `button.traffical_{ride}_check_in` | Ride | `POST /api/Mobile/CheckIn/Passenger` `{ checkIn: true, memberId, rideId }` | `gotOnRideReport.isActive`, ride not finished, not already checked in, inside policy time windows |
| `button.traffical_{ride}_check_out` | Ride | Same endpoint, `checkIn: false` | Same policy, currently checked in |
| `button.traffical_{ride}_not_coming` | Ride | `PUT /api/Mobile/Route/Change/RemovePassenger` | `notComingReport.isActive`, ride still `New`, inside `limitBeforeRide` if that limit is active |

Unavailable buttons stay on the device and are greyed out (`available = False`). Do not create check-in / not-coming buttons if the corresponding policy is off.

### Child select

`select.traffical_child`

- Options from `GET /api/Mobile/User/Roles` (`childrens`) or `GET /api/Mobile/User/ChildPassengers` if needed
- State = active child from `GET /connect/userinfo` (`person`)
- Changing the option: identity grant `switch_child`, then reload rides

**One child (or parent-as-passenger only):** entity still exists, single option, **`available = False`** (disabled). No switch UX.

---

## Sensors and binary sensors

| Entity | Role |
|--------|------|
| `sensor.traffical_next_ride` | Next (or current) ride: direction, start, my station, destination, `ride_id`, ticket, `service_date` (may be after today, up to 4 days) |
| `sensor.traffical_{ride}_status` | `New`, `Ongoing`, `OngoingMonitored`, `Finished`, `FinishedMonitored`, … |
| `binary_sensor.traffical_{ride}_checked_in` | From `CheckIn/GetStatuses` (`checkIn`, `checkInAt`); unknown if `checkIn` is null |
| `sensor.traffical_{ride}_my_station` | Assigned stop **address** (geocoded `address`; keep raw `name` as a secondary attribute), scheduled arrival, lat/lng |
| `sensor.traffical_{ride}_destination` | Destination **name** (`isTarget` stations keep `name`; expose `address` as an attribute) and scheduled arrival |
| `sensor.traffical_{ride}_driver` | Name / mobile when assigned (often empty until close to departure) |
| `sensor.traffical_{ride}_vehicle` | Plate, type, shuttle company |

Optional: delay vs schedule, progress along stations, “approaching my stop”. Policy flags can live as attributes on the **hub** so automations can `condition` on `got_on` / `not_coming`.

---

## Map

### Bus (mandatory)

`device_tracker.traffical_{ride}_bus`

- `source_type: gps`
- Updated from SignalR `ReceiveCoordinates` while live
- **Unavailable** when the ride is not live (do not leave a stale pin overnight). A finished ride may briefly show last path point, then go unavailable

### Stations: `geo_location` markers

Stations are not extra `device_tracker`s (they do not move) and not a **normal** HA zone per stop (that would steal “in zone” from people and from the bus).

One `geo_location` per station on that ride device (today’s path). They show on the default Map **only for the bound focus ride**: a live `Ongoing*` ride if any, otherwise the next unfinished **assigned today** ride (earliest start). Finished / earlier same-day rides keep their markers in the registry but unavailable. After the last **today** ride finishes, no station pins (tomorrow’s trip is not drawn on a device whose status is still Finished). Friendly name is the station **address** (it matches `lat`/`lng`); keep `name` as an extra attribute because it is often a stale dispatcher label. For `isTarget` stations, prefer **name** (school / activity) and keep `address` as an attribute. Icon and color depend on **role** and **progress**:

| Kind | Detection | Icon (example) | Color |
|------|-----------|----------------|-------|
| **Target** (school / activity) | Station `isTarget: true` | `mdi:school` | Amber |
| **Home station** | Station whose `passengers[]` contains this `memberId` | `mdi:home` | Blue |
| **Pending** | No `actualArriveDateTime` and no `ArrivedToStation` yet | `mdi:bus-stop` | Grey |
| **Passed** | `actualArriveDateTime` set **or** SignalR `ArrivedToStation` for that `stationId` | `mdi:bus-stop-uncovered` | Muted green |

If home and target are the same stop, prefer the **home** icon when it is *your* stop; otherwise school.

**Direction**

- Morning (e.g. `direction` 120): home = pickup, target = school.
- Afternoon (e.g. `direction` 121): school is **start** (`isTarget` on the first station); home is **drop-off**. Target marker is still school; home marker is still the passenger stop.

When there is no focus ride (evening / all finished / list empty), hide or **unavailable** the station markers so they do not clutter the map. Keep the **ride device**. Station ids may change; recreate markers as needed, still attached to the same ride device.

Do **not** create HA `zone` entities. Station `geo_location`s are the map pins; “van at our stop” is `traffical_approaching_stop` (or the same device trigger on the ride device).

---

## Events (bus)

Prefer HA events for transitions that should not thrash sensors:

| Event | When | Data |
|-------|------|------|
| `traffical_ride_status_changed` | List poll / status change | `ride_id`, `old`, `new`, `direction`, `key` |
| `traffical_ride_started` | First transition into `Ongoing*` | `ride_id`, `name`, `key` |
| `traffical_ride_finished` | `Finished*` | `ride_id`, `checked_in`, `key` |
| `traffical_checkin_changed` | `checkIn` flips | `ride_id`, `check_in`, `check_in_at`, `key` |
| `traffical_arrived_station` | SignalR `ArrivedToStation` | `ride_id`, `station_id`, `is_my_station`, `key` |
| `traffical_approaching_stop` | GPS vs home station | `ride_id`, `distance_m`, `key` |

`key` is the stable ride device id (`routeId:direction`). Device triggers on the **ride** device wrap the same events (Automations → Device). Raw Event triggers still work. Do not fire a bus event on every coordinate tick.

---

## Example automations

- Lights / TTS **20–30 min** before `passengerStationArrivalDateTime`
- Notify on `traffical_approaching_stop` (or the ride-device trigger **Approaching stop**)
- Notify when `driver` goes from empty to a name
- Dashboard: check-in button while live and not checked in
- Alert if still not checked in after the home/school station has `actualArriveDateTime`
- School calendar / sick → press **Not coming** on today’s rides (respect policy windows)
- `ArrivedToStation` at destination → “kid at school” / unlock / HVAC
- Ride finished and never checked in → exception notify
- Refresh token dead → HA **reauth** repair (OTP); do not spam a custom persistent notification in a loop
- `New` → `FinishedMonitored` with no `Ongoing` → “no live tracking today”

---

## Auth, persistence, and reauth

Silent **token refresh** is the normal path. **OTP reauth** is only when refresh is dead. Tokens and device identity must survive HA restart; they live on the Home Assistant config entry, not in the console `data/config.json`.

### Store (survives restart)

Persist on the **config entry `data`** (`.storage/core.config_entries`). Update it whenever tokens rotate:

`hass.config_entries.async_update_entry(entry, data={**entry.data, "tokens": new_tokens})`

A separate `helpers.storage.Store` is optional; one blob on the entry is enough.

| Field | Why |
|--------|-----|
| `environment`, `api_url`, `identity_url`, `language` | Same hosts after reboot |
| `phone` | Reauth must not ask for the number again |
| `device_id` | `authorize` sends `device_id`; a new UUID looks like a new device |
| `app_hash` | Same as engine `SessionStore` |
| `tokens` (`access_token`, `refresh_token`, `id_token`, `token_type`, `expires_in`, `obtained_at`) | Resume without OTP |
| `child_id` | Keep `select.traffical_child` after reboot |

Do **not** persist long-term: `otp_ticket`, PKCE verifier (config-flow memory only). Do not put tokens on entity attributes or in logs.

Identity often **rotates** `refresh_token`. Always write the new pair after a successful refresh. `switch_child` also returns a new token pair — persist that too, or a restart snaps back to the previous child.

On HA start / entry setup: load entry → if `refresh_token` exists, `grant_type=refresh_token` → save new tokens → `userinfo` + policies + today’s rides.

### Background refresh (no UI)

Refresh before `obtained_at + expires_in`, and on 401 from mobile/`userinfo`. If refresh returns 200, update entry data and continue. Entities stay available.

Token refresh and SignalR run as `await`s when the clients are async. If a spike still uses sync `signalrcore` / `requests`, run that I/O in an executor and never write entity state from the hub thread (see [coding.md](./standards/coding.md)).

### Reauth (OTP again)

If refresh fails (`invalid_grant`, 400/401) or there is no refresh token:

1. Raise `ConfigEntryAuthFailed` and call `entry.async_start_reauth(hass)` **once** (not on every coordinator poll).
2. HA shows the integration **reconfigure / reauth** repair.
3. User clicks it → `ConfigFlow.async_step_reauth`.
4. **That click sends OTP** — `RequestOtp` with the **stored phone** and `app_hash`. Do not wait for a second “Send code” unless the first SMS failed.
5. OTP form (`async_step_reauth_confirm`). Optional “Send again” if the ticket expired (`expiredIn`).
6. Same as first setup: authorize + PKCE + `exchange_code`.
7. `async_update_reload_and_abort` with new tokens; reload the entry.

Phone is read-only on reauth (shown as a hint). Changing number is a **new** config entry, not reauth.

While reauth is pending, the integration is unavailable (buttons, bus tracker, coordinator). Do not keep calling the mobile API.

### Config flow steps

| Step | First setup | Reauth |
|------|-------------|--------|
| Phone | User enters phone (Live hosts) | Skipped; phone from `entry.data` |
| Send OTP | After submit of phone step | **Immediately** when the user opens reauth |
| Enter OTP | `async_step_otp` | `async_step_reauth_confirm` |
| Unique id | e.g. `phone` or userinfo `sub` | Same entry (`async_set_unique_id`) |

Parents with several children use `select.traffical_child` after a valid session.

---

## Engine mapping

| Integration behavior | Engine today |
|----------------------|--------------|
| Login / session / token persist | `IdentityClient`, `SessionStore` — HA uses **config entry data** instead of `data/config.json` |
| Restart without OTP | `IdentityClient.refresh` (same as console `_try_refresh`) |
| OTP when refresh is dead | `RequestOtp` + authorize; HA **reauth** flow instead of the console phone/OTP prompts |
| Hub + ride devices | HA device registry; ride key = `routeId` + `direction`, today’s `rideId` from list/details |
| Rides + details + check-in statuses | `MobileClient.list_rides`, `ride_details`, `checkin_statuses` |
| Path snapshot | `MobileClient.monitoring_path` |
| Live GPS | `SignalRHubs.start_track` (`ReceiveCoordinates`, `ArrivedToStation`) |
| Stream ride status / route saves | `SignalRHubs.start_mobile` (`mobileHub`) |
| Auto attach/detach GPS | `App._mobile_hub_event` |
| Check-in / not coming POSTs | Documented; **not** wrapped on `MobileClient` yet |
| `switch_child` | Identity grant; **not** in the console menu yet; new tokens must be saved on the entry |
| Chat | Hub + settings; this Mashcal passenger tenant has no `rideChat` module (403) — omit until enabled |

---

## v2 (not v1)

- Hugim reservations calendar (`/api/Mobile/Reservation/Municipality…`)
- Join / shuttles (policy `joinRide` is off on this tenant)
- Ride chat notify / send when `rideChat` is on
- Notification inbox
- QR check-in / join
