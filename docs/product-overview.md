# Traffical / Shift — Product Overview

## What this is

This workspace is a **decompiled Android client** of **Mashcal Traffical** (`com.mashcal.traffical`, version **6.14.1**). It is a white-label of the **Shift / ShiftPro** mobile product (`com.shift.shiftapp`): operational software for **scheduled passenger transport** (schools, workplaces, municipalities, army), not a consumer ride-hail app like Uber.

Live API hosts are Mashcal (`mobile-traffical.mashcal.co.il`) with Shift-style identity (`identity-traffical.mashcal.co.il`). The same product family also has Shift live/stage/dev URLs.

## Problem it solves

Organizations that run daily shuttles and fixed routes need one mobile app for:

- Passengers and parents to **reserve seats** and see their rides
- Drivers and accompaniers to **run trips**, check in passengers, and report completion
- Dispatch / transportation managers to **create and change routes**
- Supervisors / commanders to **monitor** rides in near real time
- Shuttle companies to **sell leftover capacity** on a marketplace (where enabled)

## Who uses it (roles)

Users sign in once, then pick a **role** and **customer**. Supported roles include:

| Role | Typical job |
|------|-------------|
| Passenger / Parent | View rides, reserve, join, check-in status |
| Driver | Start/end trip, GPS tracking, passenger check-in, end report |
| Accompany | Escort passengers; optional work-time tracking |
| Usher | Boarding / local operations |
| Transportation manager / Customer admin / Administrative | Dispatch, route changes, approvals |
| Army section / ride commander | Army reservation and ride oversight |
| Business ride supervisor | Corporate ride supervision |

Feature visibility is driven by **customer type**, **role policies**, and **feature flags** (for example accompany change, QR join, marketplace).

## Customer / tenant types

The app adapts UI and APIs by customer type (path segment on ride list and nav graphs):

| Type | Ride-list path name | Notes |
|------|---------------------|--------|
| Business / Police / IEC / Rafael / Elbit | `Generic` | Corporate reservations, departments/shifts/branches filters |
| Army | `Army` | Army reservations, bases/tags, passenger search |
| Municipality | `Municipality` | Hugim-style activity reservations (schools/grades) |
| Transport company | `ShuttleCompany` | Fleet filters (customers, no driver/car) |

This Mashcal build is oriented around **municipality / school transport (Traffical)** with filters for department, education institution, grade, and change-approval status.

## Environments

Configured in `app/src/main/assets/environments.json`:

| Name | API | Identity |
|------|-----|----------|
| Dev | `https://dev-mobile.shiftpro.co/` | `https://id-dev.shiftlive.net/` |
| Stage | `https://stage-mobile.shiftlive.net/` | `https://id-stage.shiftlive.net/` |
| PreProd | `https://preprod-mobile.shiftpro.co/` | `https://id-preprod.shiftlive.net/` |
| HotFix (Traffical QA) | `https://mobile-traffical-qa.mashcal.co.il/` | `https://identity-traffical-qa.mashcal.co.il/` |
| Live | `https://mobile-traffical.mashcal.co.il/` | `https://identity-traffical.mashcal.co.il/` |

Default active environment is **Live**. How to combine hosts + paths, headers, and example calls: [api-reference.md — How to call: base URLs](./api-reference.md#how-to-call-base-urls).

## App architecture (client)

- **UI:** Activities + Fragments, Jetpack Navigation, bottom bar; mix of MVP presenters and ViewModels
- **Networking:** Retrofit + OkHttp (certificate pinning on some builds), RxJava and Coroutines
- **Auth:** OpenID Connect–style OTP login against a separate identity host; bearer token on mobile API; refresh / switch role / switch child
- **Realtime:** Microsoft **SignalR** (WebSocket under the hub client) — four hubs
- **Push:** OneSignal / FCM
- **Maps / location:** Google Maps, foreground + background location, `LocationWorker` (~15s) for driver coordinates
- **Support / CRM:** Intercom in-app; Planhat (`api-eu.planhat.com`) for customer success sync
- **Permissions:** location (incl. background), camera (QR), phone, notifications, vibration, wake lock

## Main screens / navigation

Entry: `SplashActivity` → environment + token → permissions/GPS → `LoginActivity` or `HomeActivity`.

`HomeActivity` chooses a nav graph by tenant:

| Graph | Typical tenant | Tabs |
|-------|----------------|------|
| `navigation_home` | Default | Rides, settings, reservations, shuttles, notifications, marketplace |
| `navigation_home_business` | Corporate | Business reservations + same core tabs |
| `navigation_home_army` | Army | Army reservations + passenger search |
| `navigation_home_hugim` | Municipality / Mashcal passenger | Hugim reservations |

Deep link: `app://reservation` opens create-reservation.

## Core user flows

### 1. Login (OTP + OpenID)

1. Enter phone → request OTP  
2. Enter code → authorize + token exchange  
3. Load userinfo, roles, policies  
4. Register device; optional health statement and language  
5. Land on home for active role/customer  

### 2. Ride list → ride details

- List rides for a selected **date** with optional filters/search  
- Realtime updates via SignalR (`UpdateRideStatus`, `RouteSuccessfulSave`)  
- Open ride → stations, map, join station, shuttle company, updates, events, chat, ride report  

### 3. Driver / accompanier loop

1. Open assigned ride  
2. Start time tracking  
3. Background GPS posts coordinates  
4. Check passengers in (manual / QR / employee number)  
5. End trip / end report; optional cancel-end  
6. Battery and GPS health reported to monitoring APIs  

Passengers and supervisors **watch** the ride via monitoring path HTTP APIs + SignalR coordinates (`Monitor` subscription for non-driver/non-accompany).

### 4. Reservations (three products)

Shared pattern: initial data → available dates → stations/shifts → city-policy validation → create/edit/delete → favorites/templates.

1. **Business** — workplace shifts and stations  
2. **Army** — bases, times, city policy  
3. **Municipality (Hugim)** — activity centers / shifts for municipal transport  

### 5. Join / shuttles

Search nearby or shuttle rides → join, join-by-QR, join-by-employee-number, waiting list.

### 6. Create / change a ride (dispatch)

- **Route builder:** stepwise wizard with `OperationGuid`; type, period, time, stations, passengers, vehicle, contract, shuttle company, comment → save  
- **Route change:** after-the-fact changes (time, passengers, accompany, supervisor, cancel, shuttle) with optional approval  

### 7. Marketplace

Sellers list capacity lots from rides; buyers place offers. REST for CRUD; SignalR for live lot/bid status.

### 8. Incidents / events

On a ride: list subjects, assignees, create event, add comments (HTTP). Separate from ride chat.

### 9. Support extras

Intercom, Planhat, push notifications, address autocomplete.

## Realtime model (high level)

Not a custom raw WebSocket API. SignalR hubs:

| Hub suffix | Purpose |
|------------|---------|
| `mobileHub` | Ride list status + successful route save |
| `MobileDashboardHub` | Live map coordinates + arrived-at-station |
| `mobileRideChatHub` | In-ride chat send/receive/delete |
| `mobileMarketplaceHub` | Lot status and buyer lot updates |

Push (OneSignal/FCM) is a separate channel from these hubs.

## What this codebase is (and is not)

- **Is:** Decompiled Java sources of the Android app, useful for understanding product behavior, API contracts, and flows  
- **Is not:** The backend server, OpenAPI specs, or an easily rebuildable original Kotlin/Gradle project as shipped by Shift  

For endpoint request/response shapes, see [api-reference.md](./api-reference.md).

For what a **Passenger** sees and can do (policies, tabs, flows, APIs), see [passenger-experience.md](./passenger-experience.md).
