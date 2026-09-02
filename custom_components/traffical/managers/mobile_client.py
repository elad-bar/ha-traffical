"""Mobile REST client (HA-free)."""

from __future__ import annotations

from typing import Any

from ..models.rides import rides_customer_type
from .api_client import ApiClient

__all__ = ["MobileClient", "rides_customer_type"]


class MobileClient(ApiClient):
    async def user_roles(self) -> Any:
        data = await self.get(
            "/api/Mobile/User/Roles",
            auth=True,
            action="user_roles",
        )
        return data if data is not None else []

    async def child_passengers(self) -> Any:
        data = await self.get(
            "/api/Mobile/User/ChildPassengers",
            auth=True,
            action="child_passengers",
        )
        return data if data is not None else []

    async def passenger_policies(self) -> Any:
        data = await self.get(
            "/api/Mobile/Policies/Passenger",
            auth=True,
            action="passenger_policies",
        )
        return data if data is not None else {}

    async def list_rides(self, customer_type: str, date: str) -> Any:
        data = await self.post_json(
            f"/api/Mobile/Rides/{customer_type}",
            {"date": date},
            auth=True,
            action="list_rides",
        )
        return data if data is not None else []

    async def ride_details(self, ticket: str) -> Any:
        data = await self.get(
            "/api/Mobile/Rides",
            params={"ticket": ticket},
            auth=True,
            action="ride_details",
        )
        return data if data is not None else {}

    async def checkin_statuses(self, ride_ids: list[int]) -> Any:
        data = await self.post_json(
            "/api/Mobile/CheckIn/GetStatuses",
            ride_ids,
            auth=True,
            action="checkin_statuses",
        )
        return data if data is not None else []

    async def monitoring_path(self, ride_id: int) -> Any:
        data = await self.get(
            "/api/Mobile/RideMonitoringPath/Get",
            params={"rideId": ride_id},
            auth=True,
            action="monitoring_path",
        )
        return data if data is not None else []

    async def check_in_passenger(
        self, ride_id: int, member_id: int, check_in: bool
    ) -> Any:
        return await self.post_json(
            "/api/Mobile/CheckIn/Passenger",
            {"checkIn": check_in, "memberId": member_id, "rideId": ride_id},
            auth=True,
            action="checkin_passenger",
        )

    async def remove_passenger(
        self,
        route_id: int,
        passenger_id: int,
        date_from: str,
        date_to: str | None = None,
    ) -> Any:
        return await self.put_json(
            "/api/Mobile/Route/Change/RemovePassenger",
            {
                "routeId": route_id,
                "value": {
                    "passengerId": passenger_id,
                    "dateFrom": date_from,
                    "dateTo": date_to or date_from,
                    "days": [],
                },
            },
            auth=True,
            action="remove_passenger",
        )

    async def chat_settings(self, ride_id: int) -> Any:
        data = await self.get(
            "/api/mobile/RideChat/Settings",
            params={"rideId": ride_id},
            auth=True,
            action="chat_settings",
        )
        return data if data is not None else {}

    async def chat_history(self, ride_id: int) -> Any:
        data = await self.get(
            "/api/mobile/RideChat/History",
            params={"rideId": ride_id},
            auth=True,
            action="chat_history",
        )
        return data if data is not None else []
