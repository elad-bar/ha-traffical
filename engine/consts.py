from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
CONFIG_PATH = DATA_DIR / "config.json"
DEBUG_DIR = ROOT / "debug"

CLIENT_ID = "shift-mobile"
OAUTH_SCOPE = "openid shift_mobile_api offline_access"
OTP_TICKET_HEADER = "x-otp-ticket"

DEFAULT_LANGUAGE = "he"
DEFAULT_ENVIRONMENT = "Live"
HTTP_TIMEOUT = 30

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
