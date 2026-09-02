# Traffical / Shift — API & Realtime Reference

Client contracts reconstructed from the decompiled Android app (`iShiftApiService`, `iIdentityServiceApi`, `MarketplaceApiService`, `EventsApiService`, SignalR services).

**Notes**

- These are **Gson client contracts**. The server may send extra fields.
- Unless noted, JSON keys match Java field names (or `@SerializedName` where present).
- Dates are typically ISO-like strings (`DateTime` / `Date`).
- `empty` means HTTP 2xx with no useful body (`Completable` / `Void`).
- Paths below are **relative**. Prepend the matching host from [How to call: base URLs](#how-to-call-base-urls).

---

## How to call: base URLs

There are **two hosts per environment**, not one URL per endpoint. Retrofit `baseUrl` is `api_url` (mobile) or `identity_service_url` (login). Paths in this file are appended to that host.

This Mashcal APK defaults to **Live**. Config: `app/src/main/assets/environments.json`.

### Hosts by environment

| Environment | Mobile API (`api_url`) | Identity (`identity_service_url`) |
|-------------|------------------------|-----------------------------------|
| **Live** (default) | `https://mobile-traffical.mashcal.co.il/` | `https://identity-traffical.mashcal.co.il/` |
| Traffical QA (HotFix) | `https://mobile-traffical-qa.mashcal.co.il/` | `https://identity-traffical-qa.mashcal.co.il/` |
| Dev | `https://dev-mobile.shiftpro.co/` | `https://id-dev.shiftlive.net/` |
| Stage | `https://stage-mobile.shiftlive.net/` | `https://id-stage.shiftlive.net/` |
| PreProd | `https://preprod-mobile.shiftpro.co/` | `https://id-preprod.shiftlive.net/` |

Third host (CRM only, not ride ops):

| Service | Base |
|---------|------|
| Planhat | `https://api-eu.planhat.com` |

`api_url` already ends with `/`. Paths with or without a leading `/` resolve on that host the same way, for example:

```text
{api_url} + /api/Mobile/Rides
→ https://mobile-traffical.mashcal.co.il/api/Mobile/Rides
```

### Which host for which paths

| Group | Base | Live example |
|-------|------|----------------|
| `/authorization/…`, `/connect/…` | **Identity** | `https://identity-traffical.mashcal.co.il/authorization/RequestOtp` |
| `/api/Mobile/…`, `/api/mobile/…`, `/api/Coordinates/Get` | **Mobile API** | `https://mobile-traffical.mashcal.co.il/api/Mobile/Rides/Municipality` |
| `/SaveCoordinates`, `/StopMonitoring`, `/WriteLog` | **Same mobile API** (host root, not under `/api/Mobile`) | `https://mobile-traffical.mashcal.co.il/SaveCoordinates` |
| Marketplace + Events | **Same mobile API** | `https://mobile-traffical.mashcal.co.il/api/Mobile/Marketplace/BuyerLots` |
| SignalR hubs | **Same mobile API** + hub name | `https://mobile-traffical.mashcal.co.il/mobileHub` |
| Planhat `/endusers`, `/companies` | Planhat | `https://api-eu.planhat.com/endusers` |

**SignalR (Live):**

- `https://mobile-traffical.mashcal.co.il/mobileHub`
- `https://mobile-traffical.mashcal.co.il/MobileDashboardHub`
- `https://mobile-traffical.mashcal.co.il/mobileRideChatHub`
- `https://mobile-traffical.mashcal.co.il/mobileMarketplaceHub`

The client uses Microsoft SignalR (HTTP negotiate, then WebSocket) plus `Authorization`.

### Auth and headers

**1. Identity** — no mobile bearer yet:

```http
POST https://identity-traffical.mashcal.co.il/authorization/RequestOtp
Content-Type: application/json

{ "Phone": "...", "AppHash": "..." }
```

Then authorize + `POST /connect/token` (PKCE, header `x-otp-ticket`) as in the Identity section below.

The app stores the token as `{token_type} {access_token}` (usually `Bearer` + space + access token).

**2. Mobile API** — after login:

```http
POST https://mobile-traffical.mashcal.co.il/api/Mobile/Rides/Municipality
Authorization: Bearer <access_token>
Content-Type: application/json
lang: he
Accept-Language: he

{ "date": "2026-09-02" }
```

`GET {identity}/connect/userinfo` also sends `Authorization`.

Planhat uses a **separate** `Bearer` from environment `planhat_api_token` (not in the bundled `environments.json` snippet; may come from a remote env dump).

### Mapping rule

For any path in this file:

- Starts with `/connect` or `/authorization` → prepend **identity** URL
- Planhat section → `https://api-eu.planhat.com`
- Everything else → prepend **mobile `api_url`**

---

**Shared wrappers**

Route-builder / many change APIs:

```json
{ "routeId": 0, "value": { } }
```

Header `OperationGuid` = UUID from `GET /api/mobile/RouteBuilder/New` → `guid`.

`Address`:

```json
{ "fullAddress": "", "latitude": 0.0, "longitude": 0.0, "placeId": "" }
```

Several enums (e.g. `ReservationDirection`) serialize as **integers** via custom adapters.

---

## Identity

Base: `{identity_service_url}` (see [How to call: base URLs](#how-to-call-base-urls)).

Service: `iIdentityServiceApi`

### `POST /authorization/RequestOtp`

**Body:**

```json
{ "Phone": "string", "AppHash": "string" }
```

**Response:**

```json
{ "expiredIn": 0 }
```

**Also:** response header `x-otp-ticket` is stored and sent on authorize.

### `GET /connect/authorize`

**Query:** `client_id`, `response_type=code`, `scope=openid shift_mobile_api offline_access`, `response_mode=body`, `code_challenge_method=S256`, `code_challenge`, `phone`, `otp`, `device_id`

**Header:** `x-otp-ticket`

**Response:**

```json
{ "code": "string" }
```

### `POST /connect/token` (form-urlencoded)

**Login:** `client_id`, `code`, `code_verifier`, `grant_type=authorization_code` (+ optional `redirect_uri`)

**Refresh:** `client_id`, `refresh_token`, `grant_type=refresh_token`

**Switch role:** + `CustomerId`, `role`

**Switch child:** + `child_id`

**Response:**

```json
{
  "access_token": "",
  "refresh_token": "",
  "id_token": "",
  "token_type": "",
  "expires_in": 0,
  "scope": ""
}
```

### `GET /connect/userinfo`

**Header:** `Authorization`

**Response:**

```json
{
  "sub": "",
  "person": {
    "memberId": 0,
    "personId": 0,
    "firstName": "",
    "lastName": "",
    "homeAddress": "",
    "mobile": "",
    "role": 0,
    "hasChildren": false,
    "sendAnalytics": false,
    "tags": [],
    "branchId": 0
  },
  "parent": {
    "personId": 0,
    "firstName": "",
    "lastName": "",
    "mobile": ""
  },
  "customer": {
    "isMaster": false,
    "customerId": 0,
    "customerGuid": "",
    "name": "",
    "type": 0,
    "selfShuttleCompanyId": -1
  },
  "modules": {},
  "permissions": [""]
}
```

### `GET /connect/logout`

**Query:** `client_id`, `id_token_hint` → **empty**

---

## Mobile API — Account & policies

Base: `{api_url}`. Service: `iShiftApiService`.

Service: `iShiftApiService`

| Method | Path | Request | Response |
|--------|------|---------|----------|
| POST | `/api/mobile/Manage/Register` | `{ token, appVersion, platformVersion, platform, deviceModel }` | empty |
| POST | `/api/Mobile/Manage/UserLanguage` | query `language` | empty |
| GET | `/api/Mobile/User/Roles` | — | `[{ customerId, name, roles:[{roleId,name}], childrens:[{firstName,lastName,memberId}] }]` |
| GET | `/api/Mobile/User/ChildPassengers` | — | `[{ customerId, name, children:[…] }]` |
| GET | `/api/Mobile/Policies/Passenger` | — | `PassengerPolicy` |
| GET | `/api/Mobile/CustomersPolicies/Passenger` | query `id` (list) | `[PassengerPolicy]` |
| GET | `/api/Mobile/Policies/Driver` | query `customerId` | `DriverPolicy` |
| GET | `/api/Mobile/CustomersPolicies/Driver` | query `id` | `[DriverPolicy]` |
| GET | `/api/Mobile/Policies/Supervisor` | — | `SupervisorPolicy` |
| GET | `/api/Mobile/Policies/Commander` | — | `SupervisorPolicy` |
| GET | `/api/Mobile/CustomersPolicies/Supervisor` | query `id` | `[SupervisorPolicy]` |
| GET | `/api/Mobile/CustomersPolicies/Commander` | query `id` | `[SupervisorPolicy]` |
| GET | `/api/Mobile/Policies/Accompany` | — | `{ trackWorkingTime: { isActive, limitBeforeRide, limitAfterRide } }` |
| POST | `/api/Mobile/HealthStatement/Save` | empty body | empty |

**PassengerPolicy (shape):**

```json
{
  "customerId": 0,
  "isReservationEnabled": false,
  "showOtherPassengersOnRide": false,
  "gotOnRideReport": {},
  "notComingReport": {},
  "joinRide": {},
  "reservation": { "allowedActions": 0, "isActive": false }
}
```

**DriverPolicy:** `{ customerId, isDriverReportOnPassengerActive, isDriverReportRideEndActive, timeTrackingLimitSeconds, isTimeTrackingActive }`

**SupervisorPolicy:** `{ customerId, isActive, isTimeTrackingActive, timeTrackingLimitSeconds }`

**LimitationPolicy:** `{ isActive, days, hours, milliseconds }`

---

## Rides list & details

### `POST /api/Mobile/Rides/{customerType}`

Path `customerType`: `Generic` | `Army` | `Municipality` | `ShuttleCompany`

**Body (optional filters):**

```json
{
  "date": "yyyy-MM-dd",
  "routeIds": [0],
  "approvalStatus": 0,
  "search": "",
  "departments": [],
  "shifts": [],
  "branches": [],
  "customers": [],
  "direction": 0,
  "noDriver": true,
  "noCar": true,
  "schools": [],
  "grades": [],
  "tags": [],
  "bases": []
}
```

**Response:** `[Ride]`

```json
{
  "activeDays": [0],
  "assignmentDate": "",
  "checkInState": { "checkIn": false, "checkInAt": "", "rideId": 0 },
  "contactMobile": "",
  "contactName": "",
  "customerId": 0,
  "direction": 0,
  "endDate": "",
  "flightNumber": "",
  "flightTime": "",
  "isEditable": false,
  "isFavorite": false,
  "isQRScanActive": false,
  "name": "",
  "number": "",
  "numberOfPassengers": 0,
  "rideActivities": {},
  "rideInfo": {
    "accompany": "",
    "accompanyId": 0,
    "driver": "",
    "driverId": 0,
    "driverMobile": "",
    "endDateTime": "",
    "freeSeats": 0,
    "hasAccompany": false,
    "isFullManual": false,
    "isRideEndReported": false,
    "needAccompany": false,
    "passengerDestinationArrivalDateTime": "",
    "passengerDestinationName": "",
    "passengerStationArrivalDateTime": "",
    "passengerStationName": "",
    "rideId": 0,
    "rideTicket": "",
    "shuttleCompany": "",
    "shuttleCompanyId": 0,
    "startDateTime": "",
    "supervisorId": 0,
    "supervisor": "",
    "vehicle": {
      "carId": 0,
      "carSizeType": 0,
      "carTypeId": 0,
      "carTypeName": "",
      "number": "",
      "seatsCount": 0
    }
  },
  "rideUpdates": { "changeIds": [], "needsApproval": false, "routeId": 0 },
  "routeBuilderType": "",
  "routeId": 0,
  "routeOwnerName": "",
  "startDate": "",
  "status": "",
  "isAssignedToRoute": false
}
```

| Method | Path | Request | Response |
|--------|------|---------|----------|
| GET | `/api/Mobile/Rides` | query `ticket` | `RideDetails` (stations, driver, accompany, polyline, waypoints, times, tracking flags, …) |
| POST | `/api/Mobile/Rides/GetTargetData` | query `rideId`, `passengerId` | `RideTargets` |
| POST | `/api/Mobile/Activities/GetTempCommentsSummary` | query `activeDate`, body `[rideIds]` | `[{ commentIds, lastTempComment, routeId }]` |
| GET | `/api/Mobile/Activities/GetTempComments` | query `routeId`, `activeDate` | `[{ commentId, commentText, deleted, endDate, isNeedToHighlight, routeId, startDate }]` |
| POST | `/api/Mobile/RoutesAudit/GetChanges` | query `date`, body `[routeIds]` | `[RideUpdates]` |
| POST | `/api/Mobile/RoutesAudit/Get` | query `date`, body `[long routeIds]` | `[RouteAudit]` |
| POST | `/api/Mobile/CheckIn/GetStatuses` | body `[rideId ints]` | `[{ checkIn, checkInAt, rideId }]` |
| GET | `/api/Mobile/CustomerData/GetCustomerData` | query `types` | `{ branches, departments, grades, schools, shifts, shuttlecompanycustomers, tags }` |
| GET | `/api/Mobile/MasterCustomer/Branches` | query `customerIds` | `[FilterDataValue]` |
| GET | `/api/Mobile/MasterCustomer/Tags` | query `customerIds` | `[FilterDataValue]` |

**RideDetails (top-level fields):** `rideId`, `rideTicket`, `routeId`, `name`, `customerId`, `direction`, `status`, `startDate`, `endDate`, `startTime`, `endTime`, `activeDays`, `stations`, `waypoints`, `encodedPolyline`, `driver`, `accompany`, `carId`, `carNumber`, `carTypeId`, `carCapacity`, `freeSeats`, `passengersCount`, `contactName`, `contactMobile`, `shuttleCompanyName`, `shuttleCompanyContacts`, `routeItems`, `routeBuilderType`, `isTimeTrackingStarted`, `isDriverTimeTrackingStarted`, `isQRScanActive`, `isMasterCustomer`, `area`, `platform`, …

---

## Check-in / tracking / GPS

| Method | Path | Request | Response |
|--------|------|---------|----------|
| POST | `/api/Mobile/CheckIn/Passenger` | `{ checkIn, memberId, rideId }` | empty |
| POST | `/api/Mobile/CheckIn/RidePassenger` | `{ checkIn, ridePassengerId }` | empty |
| PUT | `/api/Mobile/RideTimeTracking/Start` | `{ rideId, routeId }` | empty |
| PUT | `/api/Mobile/RideTimeTracking/End` | `{ rideId, routeId }` | empty |
| PUT | `/api/Mobile/RideTimeTracking/Reset` | `{ rideId, routeId }` | empty |
| PUT | `/api/Mobile/DriverRideTimeTracking/Start` | `{ rideId, routeId }` | empty |
| PUT | `/api/Mobile/DriverRideTimeTracking/End` | `{ distanceKm, rideId, routeId }` | empty |
| PUT | `/api/Mobile/DriverRideTimeTracking/Reset` | `{ rideId, routeId }` | empty |
| PUT | `/api/Mobile/RideReport/RideEnd` | `{ customerId, passengerIdentifier, rideId }` | empty |
| PUT | `/api/Mobile/RideReport/CancelRideEnd` | `{ rideId }` | empty |
| POST | `/api/Mobile/AccompanyTime/Start/{rideId}` | — | empty |
| POST | `/api/Mobile/AccompanyTime/End` | `{ Duration, rideId }` | empty |
| POST | `/SaveCoordinates` | `{ DeviceId, Latitude, Longitude, MemberId, RideId, SourceType, SpeedKph, Heading }` | empty |
| GET | `/api/Coordinates/Get` | query `rideId` | `[MonitoredPaths]` |
| GET | `/api/Mobile/RideMonitoringPath/Get` | query `rideId` | `[MonitoredPaths]` |
| GET | `/api/Mobile/Monitoring/Tasks` | query `deviceId` | `[MonitoringTask]` |
| POST | `/api/Mobile/Monitoring/BatteryLevel` | `{ deviceId, batteryLevel }` | empty |
| POST | `/api/Mobile/Monitoring/GpsState` | `{ deviceId, isGpsActive }` | empty |
| POST | `/StopMonitoring` | `{ RideId }` | empty |
| POST | `/WriteLog` | header `DeviceId`; body `{ "Level", "Message" }` | `{ code, message }` |

---

## Join / shuttles / search

| Method | Path | Request | Response |
|--------|------|---------|----------|
| POST | `/api/Mobile/RidesSearch/GetRidesToJoin` | `{ branchId, date, latitude, longitude, maxDistance, routeDirection, timeFrom, timeTo, whenType }` | `[JoinRide]` |
| POST | `/api/mobile/ShuttleRides/Get` | `{ "date": "…" }` | `[JoinRide]` |
| POST | `/api/Mobile/RidesSearch/GetClosestRides` | `{ baseId, date, direction, distanceLimit, expectedArrivals, sourceStationCoords }` | `[SearchRideArmy]` |
| GET | `/api/Mobile/RidesSearch/GetExternalPassengerRide` | query `guid` | `{ endDateTime, rideId, ridePassengerId, routeName, routeNumber, seatsAmount, startDateTime, vehicleNumber }` |
| PUT | `/api/Mobile/Route/Change/JoinRide` | `{ routeId, value: { rideId, branchId, passengerStationId } }` | empty |
| PUT | `/api/Mobile/Route/Change/JoinRideByQr` | same as JoinRide | empty |
| PUT | `/api/mobile/Route/Change/JoinRideByEmployeeNumber` | `{ routeId, value: { rideId, employeeNumber, routeCustomerId } }` | empty |
| PUT | `/api/Mobile/Route/Change/WaitingList/AddPassenger` | `{ routeId, value: { branchId, passengerStationId, rideId } }` | empty |
| PUT | `/api/Mobile/Route/Change/WaitingList/RemovePassenger` | `{ routeId, value: { rideId } }` | empty |

**JoinRide (selected fields):** `availableSeats`, `carNumber`, `carTypeName`, `checkIn`, `checkInAt`, `customerId`, `direction`, `endDateTime`, `isFavorite`, `isJoined`, `number`, `orderOnWaitingList`, passenger station/destination names & times, `rideId`, `rideStatus`, `rideTicket`, `routeBuilderType`, `routeId`, `routeName`, `seatsCount`, `startDateTime`, `statusOnWaitingList`, `waitingListCount`, flight fields, …

---

## Route changes

Envelope: `{ "routeId": 0, "value": { "type", "dateFrom", "dateTo", "days": [], "comment", … } }`

`value` extras by change type:

- **Add passenger:** `passengerId`, `customerId`, `targetRideStationId`, `branchId`
- **Remove passenger:** `passengerId`, `removeStation`, `removeTarget`, `cancelRideIfNotValid`
- **Accompany:** `accompanyId`
- **Time:** `time`, `timeType`

| PUT path | Typical `value` |
|----------|-----------------|
| `/api/Mobile/Route/Change/AddPassenger` | PassengerCreateChange |
| `/api/Mobile/Route/Change/RemovePassenger` | PassengerRemoveCreateChange |
| `/api/Mobile/Route/Change/Accompany` | AccompanyCreateChange |
| `/api/Mobile/Route/Change/AccompanyReset` | BaseCreateChange |
| `/api/mobile/Route/Change/Accompany/SetRequired` | BaseCreateChange |
| `/api/Mobile/Route/Change/Time` | TimeCreateChange |
| `/api/Mobile/Route/Change/CancelRide` | BaseCreateChange |
| `/api/Mobile/Route/Change/ShuttleSettings` | BaseCreateChange + shuttle fields |
| `/api/Mobile/Route/Change/RemoveShuttleCompany` | BaseCreateChange |
| `/api/Mobile/Route/Change/AddSupervisor` | BaseCreateChange + supervisor |
| `/api/Mobile/Route/Change/RemoveSupervisor` | BaseCreateChange |
| `/api/Mobile/Route/Change/SetSupervisor` | BaseCreateChange |

All return **empty**.

| Method | Path | Request | Response |
|--------|------|---------|----------|
| POST | `/api/mobile/Approval/Save` | `{ approvalState, changeLogId, memberId, role }` | empty |
| POST | `/api/Mobile/RouteChangeValidation/Car` | `{ routeId, value: ValidateCar }` | empty |
| POST | `/api/Mobile/RouteChangeValidation/Driver` | `{ routeId, value: { assignmentMode, dateFrom, dateTo, days, driverId, shuttleCompanyId, type } }` | empty |
| GET | `/api/Mobile/Passengers/AssignedOnRide` | query `rideId` | `AssignedPassengersResponse` |
| GET | `/api/Mobile/Route/RideSupervisors` | query `routeId`, `activeDate` | `RideSupervisorResponse` |
| POST | `/api/Mobile/Route/Favorite/{routeId}` | — | empty |
| DELETE | `/api/Mobile/Route/Favorite/{routeId}` | — | empty |

---

## Route builder

Header: `OperationGuid` (except where noted). Envelope `{ routeId, value }` unless noted. **Response empty** except GET/New/CustomerData/contracts/vehicles/passengers search.

| Method | Path | `value` / notes |
|--------|------|-----------------|
| GET | `/api/mobile/RouteBuilder/New?routeTypeId=` | **Response `NewRouteData`:** `{ guid, isActive, details, activeRide, settings }` |
| GET | `/api/mobile/RouteBuilder/SelectDay` | query `routeId` → `NewRouteData` |
| GET | `/api/mobile/RouteBuilder/CustomerData?types=` | `{ departments, orderPurposes, routeTypes, shuttleCompanies, vehicleTypes }` |
| POST | `/api/mobile/RouteBuilder/Save` | `{ routeId }` |
| PUT | `/api/mobile/RouteBuilder/RouteType` | `{ routeTypeId }` |
| PUT | `/api/mobile/RouteBuilder/Period` | `{ dateFrom, dateTo, days }` |
| PUT | `/api/mobile/RouteBuilder/Time` | `{ dateFrom, dateTo, days, time, timeType, type }` |
| PUT | `/api/mobile/RouteBuilder/Department` | `{ departmentId }` |
| PUT | `/api/mobile/RouteBuilder/OrderPurpose` | `{ orderPurposeId }` |
| PUT | `/api/mobile/RouteBuilder/RouteItem` | `{ routeTypeItemId, values: [] }` |
| PUT | `/api/mobile/RouteBuilder/Comment` | `{ comment }` |
| PUT | `/api/mobile/RouteBuilder/ContactName` | `{ contactName }` |
| PUT | `/api/mobile/RouteBuilder/ContactMobile` | `{ contactMobile }` |
| PUT | `/api/mobile/RouteBuilder/Contract` | `{ contractId, dateFrom, dateTo, days, type }` |
| PUT | `/api/mobile/RouteBuilder/CarType` | `{ carTypeId, dateFrom, dateTo, days, shuttleCompanyId, type }` |
| PUT | `/api/mobile/RouteBuilder/ShuttleCompany` | `{ shuttleCompanyId, dateFrom, dateTo, days, type }` |
| PUT | `/api/mobile/RouteBuilder/StationAddByAddress` | `{ address, dateFrom, dateTo, days, latitude, longitude, name, placeId, rideStationIds, type }` |
| PUT | `/api/mobile/RouteBuilder/StationAddByCoordinates` | `{ dateFrom, dateTo, days, latitude, longitude, rideStationIds, type }` |
| PUT | `/api/mobile/RouteBuilder/StationAddress` | `{ address, dateFrom, dateTo, days, latitude, longitude, placeId, rideId, rideStationId, type }` |
| PUT | `/api/mobile/RouteBuilder/StationCoordinates` | `{ dateFrom, dateTo, days, latitude, longitude, rideId, rideStationId, type }` |
| PUT | `/api/mobile/RouteBuilder/StationOrder` | `{ dateFrom, dateTo, days, rideId, rideStationIds, type }` |
| PUT | `/api/mobile/RouteBuilder/StationRemove` | `{ dateFrom, dateTo, days, rideId, rideStationId, type }` |
| PUT | `/api/mobile/RouteBuilder/StationRemoveTarget` | same as StationRemove |
| GET | `/api/mobile/RouteBuilder/GetShuttleCompanyContracts` | query `shuttleCompanyId`, `date` → contracts list |
| GET | `/api/mobile/RouteBuilder/GetVehicleTypes` | query `contractId` → `[VehicleTypeNewRide]` |
| GET | `/api/mobile/RouteBuilder/SearchPassengers?searchText=` | `[PassengerNewRide]` |

**NewRideDetailsResponse** includes: `routeId`, `name`, `number`, `dateFrom`/`dateTo`, `activeDays`, `routeItems`, `routeTypeId`, flight/contact/department fields, …

**ActiveRideResponse** includes: `rideId`, stations, passengers, polyline, times, vehicle/shuttle ids, cost, distance, duration, …

---

## People / fleet / geo

| Method | Path | Request | Response |
|--------|------|---------|----------|
| POST | `/api/Mobile/Persons/FindPerson` | `{ contact, identity }` | `FindPersonObject` (or empty `Maybe`) |
| POST | `/api/Mobile/Persons/FindMember` | `{ contact, identity, roleId, customerId }` | `long` member id |
| GET | `/api/Mobile/Passengers/List` | — | `[{ id, isActive, name }]` |
| GET | `/api/Mobile/Accompany/GetList` | — | `[ShortPerson]` |
| POST | `/api/Mobile/Accompany/Save` | `{ accompanyId, jobPercentage, statusId, … }` | `PersonAccompany` |
| GET | `/api/Mobile/Driver/GetList` | — | `[Driver]` |
| POST | `/api/Mobile/Driver/CreateDriver` | `{ firstName, lastName, identityCode, communications, carId, shuttleCompanyId, … }` | `PersonDriver` |
| GET | `/api/Mobile/Cars` | — | `[CarPerson]` |
| POST | `/api/Mobile/Cars` | `NewVehicle` | `NewVehicle` |
| GET | `/api/Mobile/Cars/CustomerData` | — | `{ monitoringCarStatuses, monitoringVendors, carTypes }` |
| GET | `/api/Mobile/ShuttleCompany/GetList` | — | `[ShortPerson]` |
| GET | `/api/Mobile/Geodata/Autocomplete?text=` | — | `[Address]` |
| GET | `/api/Mobile/Locations/Addresses` | — | `{ myAddress, favoriteAddresses }` |
| POST | `/api/Mobile/Locations/FavoriteAddress` | `Address` | empty |
| DELETE | `/api/Mobile/Locations/FavoriteAddress` | query `id` | empty |

**NewVehicle fields:** `carId`, `carType`, `carTypeId`, `driverIds`, `elevator`, `mileage`, `monitoringCarStatus`, `monitoringCarStatusId`, `monitoringVendor`, `monitoringVendorId`, `number`

---

## Reservations

### Business

**Create** `POST /api/Mobile/Reservation`

```json
{
  "assignOverlap": false,
  "branchId": 0,
  "dates": [],
  "direction": 0,
  "dropOffAddress": {},
  "dropOffStationId": 0,
  "pickUpAddress": {},
  "pickUpStationId": 0,
  "shiftId": 0
}
```

**List** `GET api/Mobile/Reservation/GetAll` →

```json
{
  "leaveDays": [{ "comment": "", "date": "", "type": 0, "typeName": "" }],
  "reservations": [{
    "id": "",
    "date": "",
    "direction": 0,
    "shiftId": 0,
    "shiftName": "",
    "startTime": "",
    "endTime": "",
    "branchName": "",
    "forwardSourceTitle": "",
    "forwardDestinationTitle": "",
    "backSourceTitle": "",
    "backDestinationTitle": "",
    "pickUpStatus": 0,
    "dropOffStatus": 0,
    "type": 0,
    "isEditable": false,
    "isOvernight": false,
    "addressType": 0
  }]
}
```

| Method | Path | Request | Response |
|--------|------|---------|----------|
| GET | `/api/Mobile/Reservation` | query `id` | `ReservationInformation` |
| PUT | `/api/Mobile/Reservation` | `ReservationInformation` | empty |
| POST | `/api/Mobile/Reservation/Delete` | `{ id, direction }` | empty |
| GET | `/api/Mobile/Reservation/Initial` | — | `{ addressType, isLimitByCitiesPolicy, maxDaysAhead, pickUpSettings }` |
| POST | `/api/Mobile/Reservation/GetAvailableDates` | `{ branchId, direction, dropOffAddress, dropOffStationId, pickUpAddress, pickUpStationId, shiftId }` | `[Date]` |
| GET | `/api/Mobile/Reservation/Shifts/ByDirection` | query `direction`, `branchId` | `{ shifts, favoriteShifts }` |
| GET | `api/Mobile/Reservation/Stations` | query `direction` | `{ stations, favoriteStations }` |
| GET | `api/Mobile/Reservation/IsNewReservationsAvailableNow` | — | `boolean` |
| POST | `/api/Mobile/Reservation/ValidateCityPolicy` | `ValidateCityPolicyRequest` | empty |
| POST | `/api/Mobile/Reservation/FavoriteShifts` | `{ shiftId }` | empty |
| DELETE | `/api/Mobile/Reservation/FavoriteShifts` | query `shiftId` | empty |
| POST | `/api/Mobile/Reservation/FavoriteStations` | `{ stationId, direction }` | empty |
| DELETE | `/api/Mobile/Reservation/FavoriteStations` | query `stationId`, `direction` | empty |
| POST | `/api/Mobile/Branches/Favorite` | `{ branchId }` | empty |
| DELETE | `/api/Mobile/Branches/Favorite` | query `branchId` | empty |
| GET | `/api/Mobile/Branches/List` | — | branches / activity centers |
| GET | `/api/Mobile/ReservationTemplates/List` | — | `[Template]` |
| POST | `/api/Mobile/ReservationTemplates` | `NewTemplate` | empty |
| DELETE | `/api/Mobile/ReservationTemplates` | query `templateId` | empty |

**ReservationInformation:** `id`, `branch`, `direction`, addresses, station ids, `assignOverlap`

**Shift:** `id`, `name`, `days` (`dayOfWeek`, `startTime`, `endTime`, `isOvernight`), `isForward`, `isBackward`

### Army

Same pattern under `/api/Mobile/Reservation/Army…`

Create/edit body `ReservationArmy`:

```json
{
  "id": "",
  "address": {},
  "assignOverlap": false,
  "branchId": 0,
  "date": "",
  "direction": 0,
  "shiftId": 0,
  "stationId": 0
}
```

| Method | Path | Notes |
|--------|------|-------|
| GET | `api/Mobile/Reservation/Army/GetAll` | `{ leaveDays, reservations }` |
| GET | `/api/Mobile/Reservation/Army` | query `id` |
| POST/PUT | `/api/Mobile/Reservation/Army` | create / edit |
| POST | `/api/Mobile/Reservation/Army/Delete` | `{ id, direction }` |
| GET | `/api/Mobile/Reservation/Army/Initial` | bases, stations, pickUpSettings, maxDaysAhead, city policy |
| POST | `/api/Mobile/Reservation/Army/GetAvailableDates` | → `{ backDates, forwardDates }` |
| GET | `/api/Mobile/Reservation/Army/Times` | query `date`, `direction`, `branchId` → `[{ shiftId, status, time }]` |
| GET | `api/Mobile/Reservation/Army/IsNewReservationsAvailableNow` | boolean |
| POST | `/api/Mobile/Reservation/Army/ValidateCityPolicy` | empty |

### Municipality (Hugim)

Under `/api/Mobile/Reservation/Municipality…`

**Save** `POST /api/Mobile/Reservation/Municipality`:

```json
{
  "assignOverlap": false,
  "branchId": 0,
  "shiftId": 0,
  "pickUpAddress": {},
  "pickUpDates": [],
  "pickUpStationId": 0,
  "dropOffAddress": {},
  "dropOffDates": [],
  "dropOffStationId": 0
}
```

| Method | Path | Notes |
|--------|------|-------|
| GET | `api/Mobile/Reservation/Municipality/GetAll` | reservation list |
| GET | `/api/Mobile/Reservation/Municipality` | query `id` → `EditHugimReservation` |
| PUT | `/api/Mobile/Reservation/Municipality` | edit |
| POST | `/api/Mobile/Reservation/Municipality/Delete` | delete |
| GET | `/api/Mobile/Reservation/Municipality/Initial` | activity centers initial data |
| GET | `/api/Mobile/Reservation/Municipality/Shifts` | query `branchId` |
| GET | `/api/Mobile/Reservation/Municipality/Stations` | query `direction` |
| POST | `/api/Mobile/Reservation/Municipality/GetAvailableDates` | → `{ backwardDates, forwardDates }` |
| GET | `api/Mobile/Reservation/Municipality/IsNewReservationsAvailableNow` | boolean |
| POST | `/api/Mobile/Reservation/Municipality/ValidateCityPolicy` | empty |
| POST | `/api/Mobile/Reservation/Municipality/FavoriteShifts` | `{ shiftId }` |
| DELETE | `/api/Mobile/Reservation/Municipality/FavoriteShifts` | query `shiftId` |
| POST | `/api/mobile/Reservation/Municipality/FavoriteStations` | `{ stationId, direction }` |
| DELETE | `/api/mobile/Reservation/Municipality/FavoriteStations` | query `stationId`, `direction` |

---

## Ride chat (HTTP)

| Method | Path | Request | Response |
|--------|------|---------|----------|
| GET | `/api/mobile/RideChat/History` | query `rideId` | `[{ messageId, message, createdAtUtc, senderFirstName, senderLastName, senderMemberId, senderRole }]` |
| GET | `/api/mobile/RideChat/Settings` | query `rideId` | `{ isEnabled, startDateTimeUtc, endDateTimeUtc, timeLimitBeforeRideInMinutes, timeLimitAfterRideInMinutes }` |

---

## Events

Service: `EventsApiService`

| Method | Path | Request | Response |
|--------|------|---------|----------|
| GET | `api/mobile/Events/GetByRide` | query `rideId` | `[MobileEventDto]` |
| GET | `api/mobile/Events/Subjects` | — | `[{ id, name }]` |
| GET | `api/mobile/Events/Assignees` | — | `[{ memberId, fullName, roleId, roleName }]` |
| GET | `api/mobile/Events/ReportedBy` | query `rideId` | `[EventMemberDto]` |
| POST | `api/mobile/Events/Create` | `{ rideId, routeId, subjectId, description, assigneeId, reportedById }` | `EventDto` |
| POST | `api/mobile/Events/AddComment` | `{ eventId, message, chatType }` | `{ updateId, type, message, actorMemberId, actorName, actorRoleId, createdAtUtc }` |

**MobileEventDto:** `id`, `customerId`, `customerName`, `description`, `startDateTime`, `endDateTime`, `reportedBy*`, `reportedTimeUtc`, `rideDate`, `rideId`, `routeId`, `status`, `subjectId`, `subjectName`, `isForShuttleCompany`, `updates: [EventUpdateDto]`

**EventDto:** richer create response including driver/accompany/supervisor/vehicle/shuttle metadata.

---

## Marketplace

Service: `MarketplaceApiService`

| Method | Path | Request | Response |
|--------|------|---------|----------|
| GET | `api/Mobile/Marketplace/CustomerData` | query `types` | `{ subContractors:[{ id, name }] }` |
| POST | `api/Mobile/Marketplace/GetLotDefaults` | `{ lots:[{ lotId, rideIds }] }` | lot defaults with per-ride cost/payment |
| POST | `api/Mobile/Marketplace/CreateLots` | `{ subContractorIds:[], lots:[{ lotId, lockTime, rides:[{ rideId, maxPaymentAmount }] }] }` | `{ lotsCreated, successfulRides, failedRides }` |
| GET | `api/Mobile/Marketplace/SellerLots` | — | `{ lots:[ SellerLot ] }` |
| GET | `api/Mobile/Marketplace/SellerLot` | query `lotId` | one seller lot |
| GET | `api/Mobile/Marketplace/BuyerLots` | — | `{ lots:[ BuyerLot ] }` |
| GET | `api/Mobile/Marketplace/BuyerLot` | query `lotId` | one buyer lot |
| GET | `api/Mobile/Marketplace/RidesLotStatus` | query `date` | `{ statuses:[{ rideId, lotId, status, lockTime, offersCount }] }` |
| POST | `api/Mobile/Marketplace/PlaceOffer` | query `lotId`; body `{ amount }` | empty |
| POST | `api/Mobile/Marketplace/AcceptOffer` | query `lotId`, `subContractorId` | empty |
| POST | `api/Mobile/Marketplace/CancelOffer` | query `lotId` | empty |
| POST | `api/Mobile/Marketplace/CancelLot` | query `lotId` | empty |
| POST | `api/Mobile/Marketplace/HideLot` | query `lotId` | empty |
| POST | `api/Mobile/Marketplace/RemoveLot` | query `lotId` | empty |
| POST | `api/Mobile/Marketplace/ResolveManually` | query `lotId` | empty |

**GetLotDefaults response lot:**

```json
{
  "lotId": 0,
  "lockTime": "",
  "totalMaxPayment": 0.0,
  "rides": [{
    "rideId": 0,
    "customerCost": 0.0,
    "maxPaymentAmount": 0.0,
    "profitPercentage": 0.0,
    "startDateTime": "",
    "endDateTime": "",
    "isOnActiveAuction": false
  }]
}
```

**CreateLots response:**

```json
{
  "lotsCreated": 0,
  "successfulRides": [0],
  "failedRides": [{
    "rideId": 0,
    "routeName": "",
    "routeNumber": 0.0,
    "errorCode": "",
    "errorMessage": ""
  }]
}
```

**Seller lot:** `{ lotId, lotType, status, lockTime, maxPayment, customerCost, profitPercentage, rideDate, vehicleType, acceptedSubContractorId, acceptedSubContractorName, rides:[…], offers:[{ offerAmount, offeredAt, subContractorId, subContractorName }] }`

**Buyer lot:** `{ lotId, status, myOfferAmount, myOfferTime, sellerName, lastOfferCancelReason, lastOfferCancelledAtUtc, isAccepted, lockTime, maxPayment, lotType, rideDate, vehicleType, rides:[…] }`

**Ride-in-lot:** `{ rideId, routeId, routeName, routeNumber, startDateTime, endDateTime, distance, duration, vehicleType, failed }`

---

## Planhat (CRM)

Base: `https://api-eu.planhat.com` — `iPlanhatApiService`

| Method | Path | Request | Response |
|--------|------|---------|----------|
| POST | `/endusers` | `PlanhatCompanyUser` + Auth header | empty |
| GET | `/companies?limit=5000` | Auth header | `[PlanhatCompany]` |
| GET | `/endusers?limit=2000` | Auth + query `c` | `[PlanhatCompanyUser]` |
| PUT | `/endusers/{userId}` | `PlanhatCompanyUser` | empty |

---

## SignalR / WebSocket

Not a raw `ws://` URL in app code. The Microsoft SignalR client negotiates, then uses **WebSocket** to:

```text
{api_url}{hubName}
```

Auth: `Authorization` header or access-token provider. Chat also sends header `rideId`.

### Hub names (`ConnectionType`)

| Enum | Path suffix | Purpose |
|------|-------------|---------|
| `MOBILE_HUB` | `mobileHub` | Ride list / route save |
| `MOBILE_DASHBOARD_HUB` | `MobileDashboardHub` | Live map |
| `MOBILE_RIDE_CHAT_HUB` | `mobileRideChatHub` | In-ride chat |
| `MOBILE_MARKETPLACE_HUB` | `mobileMarketplaceHub` | Auctions |

### Hub methods (`HubMethod`)

| Method | Direction | Payload |
|--------|-----------|---------|
| `UpdateRideStatus` | server → client | ride-status DTO (`UpdateRideStatus`) |
| `RouteSuccessfulSave` | server → client | `{ ChangeDateFrom, ChangeDateTo, RouteId }` |
| `ReceiveCoordinates` | server → client | `SignalRMonitoredPaths` |
| `ArrivedToStation` | server → client | `{ stationId }` (client scrolls to station) |
| `Monitor` | client → server | `rideId` (long); **not** sent for DRIVER / ACCOMPANY |
| `OnNewMessage` | server → client | chat message (same shape as history item) |
| `OnDeleteMessage` | server → client | JSON string of `messageId` |
| `SendMessage` | client → server | `(messageId, message)` |
| `DeleteMessage` | client → server | `(messageId)` |
| `UpdateLotStatus` | server → client | `{ LotId, OffersCount, RideIds, Status }` |
| `UpdateBuyerLot` | server → client | `{ LotId, Status }` |

SignalR payloads for chat/marketplace are often delivered as **JSON strings** on the hub and then `gson.fromJson`’d on the client.

### Lifecycle (client)

- `SignalRService` → `mobileHub` with home/ride list  
- `SignalRMonitoredService` → `MobileDashboardHub` on ride details  
- `ChatSignalRService` → `mobileRideChatHub` when chat opens  
- `MarketplaceSignalRService` → `mobileMarketplaceHub` on marketplace screens  

Push (OneSignal / FCM) is a **separate** channel from these hubs.

---

## Source files (primary)

| Area | Path |
|------|------|
| Main mobile API | `app/src/main/java/com/shift/shiftapp/model/services/iShiftApiService.java` |
| Identity | `app/src/main/java/com/shift/shiftapp/modules/login/service/iIdentityServiceApi.java` |
| Marketplace REST | `app/src/main/java/com/shift/shiftapp/modules/marketplace/data/source/remote/MarketplaceApiService.java` |
| Events REST | `app/src/main/java/com/shift/shiftapp/modules/ride/details/tabs/event/data/source/remote/EventsApiService.java` |
| Planhat | `app/src/main/java/com/shift/shiftapp/modules/connection/planhat/iPlanhatApiService.java` |
| Hub names | `app/src/main/java/com/shift/shiftapp/modules/connection/ConnectionType.java` |
| Hub methods | `app/src/main/java/com/shift/shiftapp/modules/connection/HubMethod.java` |
| Environments | `app/src/main/assets/environments.json` |

See also [product-overview.md](./product-overview.md) for product context and user flows.
