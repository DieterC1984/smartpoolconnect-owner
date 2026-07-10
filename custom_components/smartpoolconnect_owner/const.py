"""Constants for SmartPoolConnect Owner."""
from __future__ import annotations

DOMAIN = "smartpoolconnect_owner"
CONF_POOL_ID = "pool_id"

DEFAULT_BASE_URL = "https://www.smartpoolconnect.eu"
DEFAULT_OAUTH_BASE_URL = "https://oauth.smartpoolconnect.eu"

PUMP_SPEEDS = {
    0: "off",
    1: "low",
    2: "medium",
    3: "high",
    4: "maximum",
}
