"""Constants for SmartPoolConnect Owner Portal integration."""
from __future__ import annotations

DOMAIN = "smartpoolconnect_owner"
MANUFACTURER = "SmartPoolConnect"
CONF_POOL_ID = "pool_id"
CONF_SESSION_COOKIE = "session_cookie"
DEFAULT_BASE_URL = "https://www.smartpoolconnect.eu"
DEFAULT_OAUTH_BASE_URL = "https://oauth.smartpoolconnect.eu"
DEFAULT_SCAN_INTERVAL = 15
CLIENT_ID = "019d97d6-2f32-7deb-958b-1f76233b38ea"
REDIRECT_URI = "https://www.smartpoolconnect.eu/auth"
OAUTH_SCOPE = "email profile"
PUMP_SPEEDS = {0:"off", 1:"low", 2:"medium", 3:"high", 4:"maximum"}
PUMP_SPEEDS_REVERSE = {v:k for k,v in PUMP_SPEEDS.items()}
