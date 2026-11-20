"""Base entity for Automate Pulse PRO blinds."""
from __future__ import annotations

from homeassistant.core import callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity import Entity

from .const import DOMAIN
from .models import PulseProData


class PulseProEntity(Entity):
    """Entity updated by the shared hub connection (no per-entity polling)."""

    _attr_should_poll = False
    # Entity names are added to the device name, e.g. "Kitchen Battery"
    _attr_has_entity_name = True

    def __init__(self, data: PulseProData, blind_id: str, entry_id: str) -> None:
        self._data = data
        self._hub = data.hub
        self._blind_id = blind_id
        # The device itself (name, model, link to the hub) is created in
        # __init__.py with via_device_id. The deprecated via_device is not used.
        self._attr_device_info = DeviceInfo(identifiers={(DOMAIN, blind_id)})

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(self._hub.add_listener(self._blind_id, self._handle_update))

    @callback
    def _handle_update(self) -> None:
        self.async_write_ha_state()

    @property
    def available(self) -> bool:
        return self._hub.is_blind_available(self._blind_id)
