"""Restart button for the Pulse PRO hub (needs a smart plug, see the options)."""
from __future__ import annotations

from homeassistant.components.button import ButtonDeviceClass, ButtonEntity
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .models import PulseProConfigEntry, PulseProData


async def async_setup_entry(
    hass: HomeAssistant,
    entry: PulseProConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    data = entry.runtime_data
    if data.watchdog is not None:
        async_add_entities([PulseProRestartButton(data, entry.entry_id)])


class PulseProRestartButton(ButtonEntity):
    """Power cycle the hub with the configured smart plug."""

    _attr_has_entity_name = True
    _attr_device_class = ButtonDeviceClass.RESTART
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, data: PulseProData, entry_id: str) -> None:
        self._watchdog = data.watchdog
        self._attr_name = "Restart hub"
        self._attr_unique_id = f"{entry_id}_hub_restart"
        self._attr_device_info = DeviceInfo(identifiers={(DOMAIN, data.hub_identifier)})

    async def async_press(self) -> None:
        await self._watchdog.async_restart("manual")
