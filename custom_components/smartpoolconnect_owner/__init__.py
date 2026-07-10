"""SmartPoolConnect Owner Portal integration."""
from __future__ import annotations
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME, Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady
from .api import AuthenticationError, SmartPoolConnectClient, SmartPoolConnectError
from .const import CONF_POOL_ID, CONF_SESSION_COOKIE
from .coordinator import SmartPoolConnectCoordinator
PLATFORMS: list[Platform] = [Platform.BINARY_SENSOR, Platform.BUTTON, Platform.COVER, Platform.DATE, Platform.NUMBER, Platform.SENSOR, Platform.SWITCH, Platform.SELECT, Platform.TIME]
type SmartPoolConnectConfigEntry = ConfigEntry[SmartPoolConnectCoordinator]
async def async_setup_entry(hass: HomeAssistant, entry: SmartPoolConnectConfigEntry) -> bool:
    client = SmartPoolConnectClient(entry.data.get(CONF_USERNAME), entry.data.get(CONF_PASSWORD), pool_id=entry.data[CONF_POOL_ID], session_cookie=entry.data.get(CONF_SESSION_COOKIE))
    try:
        await client.async_login()
    except AuthenticationError as err:
        await client.close(); raise ConfigEntryAuthFailed(str(err)) from err
    except SmartPoolConnectError as err:
        await client.close(); raise ConfigEntryNotReady(str(err)) from err
    coordinator = SmartPoolConnectCoordinator(hass, client, entry)
    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True
async def async_unload_entry(hass: HomeAssistant, entry: SmartPoolConnectConfigEntry) -> bool:
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok: await entry.runtime_data.client.close()
    return unload_ok
