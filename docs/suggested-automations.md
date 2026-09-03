# Suggested automations

YAML starting points for a passenger / parent Home Assistant setup. Replace notify
targets, lights, and ride entity ids with yours. Entity ids come from the ride
device name plus the labels in the [README](../README.md#what-you-get).

This integration does **not** create Home Assistant zones. Prefer the events below
over “bus enters zone.” Station `geo_location` markers are for the map, not occupancy.

In the UI you can pick the same signals on the **ride device**
(Automations → Device). The examples use `event` so they stay readable.

Morning rides are typically home pickup → school. Afternoon rides are school →
home drop-off. Same events; different actions.

Event list and entity inventory: [README](../README.md#events-and-automations) ·
design notes: [home-assistant-integration.md](./home-assistant-integration.md).

---

## Van approaching the home stop

Fires once when live GPS is within about 80 m of the assigned stop.

```yaml
alias: Traffical — bus approaching stop
triggers:
  - trigger: event
    event_type: traffical_approaching_stop
actions:
  - action: notify.mobile_app_your_phone
    data:
      title: Shuttle
      message: "Bus is about {{ trigger.event.data.distance_m }} m from the stop."
  - action: light.turn_on
    target:
      entity_id: light.porch
```

## Bus at our stop

Slightly later than approaching — the hub marked that station passed.

```yaml
alias: Traffical — arrived at our stop
triggers:
  - trigger: event
    event_type: traffical_arrived_station
    event_data:
      is_my_station: true
actions:
  - action: notify.mobile_app_your_phone
    data:
      title: Shuttle
      message: The bus is at our stop.
```

## Ride started (live tracking)

The bus `device_tracker` is only available while the ride is live and has GPS.
Use this to open a dashboard or post a persistent notification.

```yaml
alias: Traffical — ride started
triggers:
  - trigger: event
    event_type: traffical_ride_started
actions:
  - action: persistent_notification.create
    data:
      title: Shuttle live
      message: "{{ trigger.event.data.name }}"
      notification_id: traffical_live
```

## Ride finished

Clear the live notification and porch light. Morning: kid should be at school.
Afternoon: kid should be at the door.

```yaml
alias: Traffical — ride finished
triggers:
  - trigger: event
    event_type: traffical_ride_finished
actions:
  - action: persistent_notification.dismiss
    data:
      notification_id: traffical_live
  - action: light.turn_off
    target:
      entity_id: light.porch
```

## Driver assigned

Often empty until close to departure.

```yaml
alias: Traffical — driver assigned
triggers:
  - trigger: state
    entity_id: sensor.YOUR_RIDE_driver
    from: unavailable
  - trigger: state
    entity_id: sensor.YOUR_RIDE_driver
    from: unknown
conditions:
  - condition: template
    value_template: "{{ trigger.to_state.state not in ['unknown', 'unavailable', ''] }}"
actions:
  - action: notify.mobile_app_your_phone
    data:
      title: Shuttle
      message: "Driver {{ trigger.to_state.state }} ({{ states('sensor.YOUR_RIDE_vehicle') }})"
```

## Get ready (calendar offset)

Each ride device has `calendar.traffical_{ride}_rides` (today plus the next listed day). Offset from that event, and keep a `status == New` condition so a leftover finished event does not fire.

```yaml
alias: Traffical — morning get ready
triggers:
  - trigger: calendar
    entity_id: calendar.YOUR_MORNING_RIDE_rides
    event: start
    offset: "-00:20:00"
conditions:
  - condition: state
    entity_id: sensor.YOUR_MORNING_RIDE_status
    state: New
actions:
  - action: tts.speak
    data:
      media_player_entity_id: media_player.kitchen
      message: The shuttle is coming. Shoes and bag.
```

## No live GPS today

If status jumps from `New` to `FinishedMonitored` without `Ongoing`, approaching
and map tracking will not run.

```yaml
alias: Traffical — no live tracking
triggers:
  - trigger: event
    event_type: traffical_ride_status_changed
    event_data:
      old: New
      new: FinishedMonitored
actions:
  - action: notify.mobile_app_your_phone
    data:
      title: Shuttle
      message: Today's ride finished without live tracking.
```
