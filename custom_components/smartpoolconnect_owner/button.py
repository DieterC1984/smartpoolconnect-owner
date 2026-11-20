"""Button entities."""
from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.event import async_call_later

from . import SmartPoolConnectConfigEntry
from .entity import SmartPoolConnectEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: SmartPoolConnectConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up command buttons from detected controller capabilities."""

    capabilities = (
        entry.runtime_data.data.capabilities if entry.runtime_data.data else frozenset()
    )
    entities: list[ButtonEntity] = []
    if "backwash" in capabilities:
        entities.append(StartBackwashButton(entry.runtime_data))
    if "cl_shock" in capabilities:
        entities.extend(
            (
                StartClShockButton(entry.runtime_data),
                StopClShockButton(entry.runtime_data),
            )
        )
    async_add_entities(entities)


class StartBackwashButton(SmartPoolConnectEntity, ButtonEntity):
    """Start the existing backwash command."""

    _attr_icon = "mdi:waves"
    _attr_name = "Backwash Trigger"
    _attr_translation_key = "start_backwash"

    def __init__(self, coordinator) -> None:
        super().__init__(coordinator, "start_backwash")

    async def async_press(self) -> None:
        await self.coordinator.client.async_start_backwash()
        await self.coordinator.async_request_refresh()


class _ClShockButton(SmartPoolConnectEntity, ButtonEntity):
    """Shared non-blocking delayed refresh behavior for Cl shock commands."""

    _cancel_delayed_refresh = None

    def _schedule_delayed_shock_refresh(self) -> None:
        """Request another status refresh about five seconds after a command."""

        if self._cancel_delayed_refresh is not None:
            self._cancel_delayed_refresh()

        async def delayed_refresh(_now) -> None:
            self._cancel_delayed_refresh = None
            await self.coordinator.async_request_refresh()

        self._cancel_delayed_refresh = async_call_later(
            self.hass, 5.0, delayed_refresh
        )
        self.async_on_remove(self._cancel_delayed_refresh)


class StartClShockButton(_ClShockButton):
    """Start Cl shock treatment without starting the filter pump."""

    _attr_icon = "mdi:flask-outline"
    _attr_name = "Start Cl Shock Treatment"
    _attr_translation_key = "start_cl_shock"

    def __init__(self, coordinator) -> None:
        super().__init__(coordinator, "start_cl_shock")

    async def async_press(self) -> None:
        # The confirmed backend command intentionally controls shock treatment
        # only. A waiting treatment is started later by the controller when its
        # filter pump starts; this integration never starts that pump here.
        await self.coordinator.client.async_start_cl_shock()
        self._schedule_delayed_shock_refresh()
        await self.coordinator.async_request_refresh()


class StopClShockButton(_ClShockButton):
    """Stop active or pump-waiting Cl shock treatment."""

    _attr_icon = "mdi:stop-circle-outline"
    _attr_name = "Stop Cl Shock Treatment"
    _attr_translation_key = "stop_cl_shock"

    def __init__(self, coordinator) -> None:
        super().__init__(coordinator, "stop_cl_shock")

    async def async_press(self) -> None:
        await self.coordinator.client.async_stop_cl_shock()
        self._schedule_delayed_shock_refresh()
        await self.coordinator.async_request_refresh()
