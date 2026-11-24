"""Online status of Automate Pulse PRO blinds, as reported by the hub."""
from __future__ import annotations

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .entity import PulseProStatusEntity
from .models import PulseProConfigEntry, PulseProData


async def async_setup_entry(
    hass: HomeAssistant,
    entry: PulseProConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    data = entry.runtime_data
    if not data.use_websocket:
        return
    async_add_entities(PulseProOnline(data, b, entry.entry_id) for b in data.blinds)


class PulseProOnline(PulseProStatusEntity, BinarySensorEntity):
    """Whether the hub considers the blind online (diagnostic).

    "Off" means the hub isn't hearing the motor: commands usually still work,
    but positions and battery values are not updated.
    """

    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY

    def __init__(self, data: PulseProData, blind_id: str, entry_id: str) -> None:
        super().__init__(data, blind_id, entry_id)
        self._attr_name = "Online"
        self._attr_unique_id = f"{entry_id}_online_{blind_id}"

    @property
    def available(self) -> bool:
        return self._has_status(self._hub.online)

    @property
    def is_on(self) -> bool | None:
        return self._hub.online.get(self._blind_id)
