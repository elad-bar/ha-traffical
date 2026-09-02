from __future__ import annotations

from typing import Any

from engine.api_client import ApiClient
from engine.consts import CUSTOMER_TYPE_PATHS, DEFAULT_RIDES_CUSTOMER_TYPE


def rides_customer_type(customer_type_id: Any) -> str:
    try:
        type_id = int(customer_type_id)
    except (TypeError, ValueError):
        return DEFAULT_RIDES_CUSTOMER_TYPE
    return CUSTOMER_TYPE_PATHS.get(type_id) or DEFAULT_RIDES_CUSTOMER_TYPE


class MobileClient(ApiClient):
    def user_roles(self) -> Any:
        resp = self.get(
            "/api/Mobile/User/Roles",
            auth=True,
            action="user_roles",
            debug_name="mobile_user_roles",
        )
        return resp.json() if resp.content else []

    def passenger_policies(self) -> Any:
        resp = self.get(
            "/api/Mobile/Policies/Passenger",
            auth=True,
            action="passenger_policies",
            debug_name="mobile_passenger_policies",
        )
        return resp.json() if resp.content else {}

    def list_rides(self, customer_type: str, date: str) -> Any:
        resp = self.post_json(
            f"/api/Mobile/Rides/{customer_type}",
            {"date": date},
            auth=True,
            action="list_rides",
            debug_name="mobile_rides_list",
        )
        return resp.json() if resp.content else []

    def ride_details(self, ticket: str) -> Any:
        resp = self.get(
            "/api/Mobile/Rides",
            params={"ticket": ticket},
            auth=True,
            action="ride_details",
            debug_name="mobile_ride_details",
        )
        return resp.json() if resp.content else {}

    def checkin_statuses(self, ride_ids: list[int]) -> Any:
        resp = self.post_json(
            "/api/Mobile/CheckIn/GetStatuses",
            ride_ids,
            auth=True,
            action="checkin_statuses",
            debug_name="mobile_checkin_statuses",
        )
        return resp.json() if resp.content else []

    def monitoring_path(self, ride_id: int) -> Any:
        resp = self.get(
            "/api/Mobile/RideMonitoringPath/Get",
            params={"rideId": ride_id},
            auth=True,
            action="monitoring_path",
            debug_name="mobile_monitoring_path",
        )
        return resp.json() if resp.content else []

    def chat_settings(self, ride_id: int) -> Any:
        resp = self.get(
            "/api/mobile/RideChat/Settings",
            params={"rideId": ride_id},
            auth=True,
            action="chat_settings",
            debug_name="mobile_chat_settings",
        )
        return resp.json() if resp.content else {}

    def chat_history(self, ride_id: int) -> Any:
        resp = self.get(
            "/api/mobile/RideChat/History",
            params={"rideId": ride_id},
            auth=True,
            action="chat_history",
            debug_name="mobile_chat_history",
        )
        return resp.json() if resp.content else []
