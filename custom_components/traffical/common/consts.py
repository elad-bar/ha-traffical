"""Shared constants (HA-free)."""

from __future__ import annotations

from datetime import timedelta
from pathlib import Path

DOMAIN = "traffical"
MANUFACTURER = "Traffical"

CLIENT_ID = "shift-mobile"
OAUTH_SCOPE = "openid shift_mobile_api offline_access"
OTP_TICKET_HEADER = "x-otp-ticket"

DEFAULT_LANGUAGE = "he"
DEFAULT_ENVIRONMENT = "Live"
HTTP_TIMEOUT = 30
SIGNALR_RECORD_SEP = "\x1e"
DASHBOARD_HUB = "MobileDashboardHub"
MOBILE_HUB = "mobileHub"

DEFAULT_RIDES_CUSTOMER_TYPE = "Municipality"
CUSTOMER_TYPE_PATHS: dict[int, str] = {
    27: "ShuttleCompany",
    28: "Municipality",
    219: "Generic",
    262: "Army",
    263: "Generic",
    264: "Generic",
    265: "Generic",
    266: "Generic",
}

ENVIRONMENTS: dict[str, dict[str, str]] = {
    "Live": {
        "api_url": "https://mobile-traffical.mashcal.co.il/",
        "identity_url": "https://identity-traffical.mashcal.co.il/",
    },
    "QA": {
        "api_url": "https://mobile-traffical-qa.mashcal.co.il/",
        "identity_url": "https://identity-traffical-qa.mashcal.co.il/",
    },
    "Dev": {
        "api_url": "https://dev-mobile.shiftpro.co/",
        "identity_url": "https://id-dev.shiftlive.net/",
    },
    "Stage": {
        "api_url": "https://stage-mobile.shiftlive.net/",
        "identity_url": "https://id-stage.shiftlive.net/",
    },
    "PreProd": {
        "api_url": "https://preprod-mobile.shiftpro.co/",
        "identity_url": "https://id-preprod.shiftlive.net/",
    },
}

CONF_PHONE = "phone"
CONF_ENVIRONMENT = "environment"
CONF_API_URL = "api_url"
CONF_IDENTITY_URL = "identity_url"
CONF_LANGUAGE = "language"
CONF_DEVICE_ID = "device_id"
CONF_APP_HASH = "app_hash"
CONF_TOKENS = "tokens"
CONF_CHILD_ID = "child_id"
CONF_POLL_INTERVAL = "poll_interval"

POLL_INTERVAL = timedelta(minutes=3)
POLL_INTERVAL_FAST = timedelta(seconds=45)
FAST_WINDOW = timedelta(minutes=30)
RIDES_LOOKAHEAD_DAYS = 4
ATTR_LATITUDE = "latitude"
ATTR_LONGITUDE = "longitude"

EVENT_RIDE_STATUS_CHANGED = "traffical_ride_status_changed"
EVENT_RIDE_STARTED = "traffical_ride_started"
EVENT_RIDE_FINISHED = "traffical_ride_finished"
EVENT_CHECKIN_CHANGED = "traffical_checkin_changed"
EVENT_ARRIVED_STATION = "traffical_arrived_station"
EVENT_APPROACHING_STOP = "traffical_approaching_stop"

STATUS_LIVE = frozenset({"ongoing", "ongoingmonitored"})
STATUS_FINISHED = frozenset({"finished", "finishedmonitored"})

PLATFORMS = (
    "sensor",
    "binary_sensor",
    "button",
    "select",
    "device_tracker",
    "geo_location",
)

REPO_ROOT = Path(__file__).resolve().parents[3]
DATA_DIR = REPO_ROOT / "data"
CONFIG_PATH = DATA_DIR / "config.json"
DEBUG_DIR = REPO_ROOT / "debug"
