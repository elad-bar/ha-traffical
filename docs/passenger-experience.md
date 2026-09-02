# Passenger experience

What the **Passenger** role sees and can do in Traffical / Shift. Dispatch, driver operations, and marketplace selling are out of scope unless a policy explicitly turns something on.

Related: [product-overview.md](./product-overview.md) · [api-reference.md](./api-reference.md)

---

## Mental model

A passenger is someone **assigned to (or joining) scheduled routes**, not someone who runs the fleet.

Typical day:

1. Open the app → list of **my rides for a date**
2. Open a ride → **my station, times, vehicle, live map**
3. Optional: **I’m on / I’m not coming**, **join another shuttle**, **reserve a seat**
4. Get push/notifications when something changes

Parents are a related case: a passenger with children can switch to a child via identity grant `switch_child`.

What you actually get is gated by **`PassengerPolicy`** (loaded after login from `GET /api/Mobile/Policies/Passenger` and per-customer `CustomersPolicies/Passenger`). The same passenger role can look very different per customer.

### `PassengerPolicy` switches

| Field | Effect |
|-------|--------|
| `isReservationEnabled` / `reservation.isActive` | Reservations tab and booking |
| `reservation.allowedActions` | Create/edit only if `AllActions` |
| `joinRide.isActive` | Join in advance + (with shuttle permission) Shuttles tab |
| `joinRide.isQrScanActive` | Join at boarding (QR) |
| `joinRide.hasShuttlePermission` | Shuttles tab (together with join active) |
| `joinRide.limitBeforeRide` | Time window for joining |
| `gotOnRideReport.isActive` | “I got on” check-in |
| `gotOnRideReport.isQrScanActive` | Check-in via QR |
| `gotOnRideReport.limitBeforeRide` / `limitAfterRide` | Check-in time windows |
| `notComingReport.isActive` | “I’m not coming” |
| `notComingReport.limitBeforeRide` | Deadline to cancel attendance |
| `showOtherPassengersOnRide` | See other people on the ride |

`LimitationPolicy`: `{ isActive, days, hours, milliseconds }`.

---

## Home screen

If the active role is `PASSENGER`, home uses a passenger nav graph:

| This Traffical (Mashcal) build | Other Shift flavors |
|--------------------------------|---------------------|
| Hugim: rides, **municipality reservations**, settings, shuttles*, notifications, marketplace* | Business or Army reservation graphs |

`HomeActivity` then **hides** tabs unless policy/config allows them:

| Tab | Shown when |
|-----|------------|
| **Rides** | Always (start destination) |
| **Reservations** | Reservation policy active |
| **Shuttles** | `joinRide.isActive` **and** `joinRide.hasShuttlePermission` |
| **Search** | Army passenger search; only if that customer has army search enabled (not typical for Mashcal) |
| **Notifications** | Present on the graph |
| **Settings** | Always |
| **Marketplace** | Hidden for passengers in this Mashcal app (Shift + transport-company + non-driver only) |

Ride **cards** use `ItemRidePassenger`, not the driver/manager card.

The list **drops rides with 0 passengers** and cancelled rides for this role, so the passenger mainly sees rides they belong on.

### Plus (+) menu

From `PlusOpportunities.setupPassengerPolicy()`:

| Action | When it appears |
|--------|-----------------|
| Create reservation | Reservation policy active **and** `allowedActions == AllActions` |
| Join in advance | `joinRide.isActive` |
| Join at boarding (QR) | `joinRide.isQrScanActive` |
| New ride | `NEW_ROUTE` feature + passenger (rare; more of a manager tool) |
| External reservation | Customer-specific config |

---

## Core flows

### 1. My rides

- Calendar / date on the ride list
- Filters (Traffical: department, school, grade, change status)
- Favorite routes
- Open ride details by `ticket`
- Live list updates via SignalR `UpdateRideStatus`

List extra data for passengers includes **check-in statuses**, not driver comments.

**APIs:** `POST /api/Mobile/Rides/{customerType}` (for Mashcal often `Municipality`), `GET /api/Mobile/Rides?ticket=`, `POST /api/Mobile/CheckIn/GetStatuses`

### 2. Ride details (consume, don’t operate)

Relevant:

- Stations and **highlight of their closest/assigned station**
- Times, vehicle, shuttle company (view)
- Map / live path — passengers **do** subscribe: SignalR `Monitor(rideId)` + `ReceiveCoordinates` / `ArrivedToStation`
- Chat (if enabled for that ride)
- Events tab (view/report depending on UI); army passengers hide the **updates** tab
- Other passengers on the ride only if `showOtherPassengersOnRide`

Not relevant (hidden or unused):

- Driver start/end time tracking, ride-end report, GPS **upload** as driver
- Checking in *other* people as usher
- Editing accompany / assigning supervisor
- Extra accompany row on the station list (passengers and parents don’t get that extra row)

Live monitoring can be blocked if the customer is configured `viewMonitoringWhenAssigned` and **this member is not on the ride**.

### 3. “I got on” / check-in

If `gotOnRideReport.isActive`:

- Mark boarded (`POST /api/Mobile/CheckIn/Passenger` with their `memberId`)
- Optionally **QR scan** if `gotOnRideReport.isQrScanActive` → `POST /api/Mobile/CheckIn/RidePassenger`
- Time windows: `limitBeforeRide` / `limitAfterRide`

### 4. “I’m not coming”

If `notComingReport.isActive` (with a before-ride time limit):

- Open a change flow that removes them from the ride (`PUT /api/Mobile/Route/Change/RemovePassenger` / “passenger not come”)

They are not doing full dispatch edits; it is “cancel myself.”

### 5. Join another ride

If join policy is on:

- Search rides to join (`POST /api/Mobile/RidesSearch/GetRidesToJoin`) or **Shuttles** tab (`POST /api/mobile/ShuttleRides/Get`)
- Join, join-by-QR, waiting list (`JoinRide`, `JoinRideByQr`, `WaitingList/*`)
- Join-in-advance vs join-at-boarding (QR) from the plus menu

### 6. Reservations (Hugim on this app)

If enabled: list / create / edit / delete municipality reservations, favorites, city-policy validation — the Hugim reservation APIs, not army/business unless that flavor of the app is used.

Deep link: `app://reservation`.

### 7. Settings and children

- Language, notifications, account
- If they have children + parent record: **switch child** (token grant `switch_child`) so the list is the child’s rides

### 8. Notifications

Passenger notification inbox is **not filtered by role** the same way as managers (all notifications for the customer).

---

## What is not the passenger product

Ignore these when thinking “passenger app”:

- Creating/changing routes as a dispatcher (except limited self-remove / rare new-route flag)
- Driver GPS `SaveCoordinates` loop (`LocationWorker` is for tracked operational roles)
- Marketplace buy/sell in this Mashcal passenger shell
- Army passenger search, kitchen/commander tools
- Approving route changes, assigning drivers/cars
- Planhat CRM admin

---

## Relevant APIs

| Need | Endpoints |
|------|-----------|
| Login / role | OTP, token, userinfo, `GET /api/Mobile/User/Roles`, `GET /api/Mobile/Policies/Passenger` |
| My rides | `POST /api/Mobile/Rides/{customerType}`, `GET /api/Mobile/Rides?ticket=`, `POST /api/Mobile/CheckIn/GetStatuses` |
| Boarded | `POST /api/Mobile/CheckIn/Passenger`, `POST /api/Mobile/CheckIn/RidePassenger` |
| Not coming | `PUT /api/Mobile/Route/Change/RemovePassenger` |
| Join / shuttles | `POST /api/Mobile/RidesSearch/GetRidesToJoin`, `POST /api/mobile/ShuttleRides/Get`, `PUT …/JoinRide*`, waiting list |
| Watch vehicle | `GET /api/Mobile/RideMonitoringPath/Get`, SignalR `MobileDashboardHub` |
| Chat | `GET /api/mobile/RideChat/History`, `GET /api/mobile/RideChat/Settings`, hub `mobileRideChatHub` |
| Reservations (if on) | `/api/Mobile/Reservation/Municipality…` |
| Device | `POST /api/mobile/Manage/Register`, language, health statement if asked |

Request/response shapes: [api-reference.md](./api-reference.md).

### SignalR that matters

| Hub | Why |
|-----|-----|
| `mobileHub` | Ride list refresh (`UpdateRideStatus`) |
| `MobileDashboardHub` | Live map (`Monitor`, `ReceiveCoordinates`, `ArrivedToStation`) |
| `mobileRideChatHub` | Only if they open ride chat |

Push (OneSignal / FCM) is a separate channel.

---

## Code entry points

| Area | Where |
|------|--------|
| Policy model | `modules/login/model/PassengerPolicy.java` (and Join/GotOn/NotComing policies) |
| Home tabs | `view/activities/HomeActivity.java` (`initBottomNavView`) |
| Plus menu | `general/PlusOpportunities.java` (`setupPassengerPolicy`) |
| Ride cards | `modules/ride/list/adapter/RideListAdapter.java` → `ItemRidePassenger` |
| List filtering | `modules/rides/presenter/RideListPresenter.java` (`shouldRemoveRide`) |
| Ride details / map gate | `modules/ride/details/view_model/RideDetailViewModel.java` (`setupViewMonitoring`) |
| Child switch | Settings + `IdentityService` grant `switch_child` |
