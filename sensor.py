"""Position and battery sensors for Automate Pulse PRO blinds."""
from __future__ import annotations

import logging

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.const import PERCENTAGE, EntityCategory, UnitOfElectricPotential
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import BATTERY_PROFILES
from .entity import PulseProEntity
from .models import PulseProConfigEntry, PulseProData

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: PulseProConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    data = entry.runtime_data
    entities: list[SensorEntity] = []
    for blind_id in data.blinds:
        entities.append(PulseProPosition(data, blind_id, entry.entry_id))
        # Mains-powered (AC) motors have no battery
        if blind_id in data.battery_blinds:
            entities.append(PulseProBattery(data, blind_id, entry.entry_id))
            entities.append(PulseProVoltage(data, blind_id, entry.entry_id))
    async_add_entities(entities)


def battery_percent(voltage: float, vmin: float, vmax: float) -> int | None:
    """Voltage -> 0-100 %. Uses the configured range, or detects the pack type."""
    if not (vmin and vmax and vmin < vmax):
        for threshold, low, high in BATTERY_PROFILES:
            if voltage > threshold:
                vmin, vmax = low, high
                break
        else:
            return None
    return round(max(0.0, min(100.0, (voltage - vmin) / (vmax - vmin) * 100)))


class PulseProPosition(PulseProEntity, SensorEntity):
    """Blind position in percent (0 = closed, 100 = open), same as the cover."""

    _attr_native_unit_of_measurement = PERCENTAGE
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_icon = "mdi:blinds"

    def __init__(self, data: PulseProData, blind_id: str, entry_id: str) -> None:
        super().__init__(data, blind_id, entry_id)
        self._attr_name = "Position"
        self._attr_unique_id = f"{entry_id}_position_{blind_id}"

    @property
    def available(self) -> bool:
        return self._hub.connected and self._blind_id in self._hub.positions

    @property
    def native_value(self) -> int | None:
        return self._hub.positions.get(self._blind_id)


class _PulseProVoltageBase(PulseProEntity, SensorEntity):
    @property
    def available(self) -> bool:
        return self._hub.connected and self._blind_id in self._hub.voltages

    @property
    def _voltage(self) -> float | None:
        return self._hub.voltages.get(self._blind_id)


class PulseProBattery(_PulseProVoltageBase):
    """Battery level in percent."""

    _attr_device_class = SensorDeviceClass.BATTERY
    _attr_native_unit_of_measurement = PERCENTAGE
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, data: PulseProData, blind_id: str, entry_id: str) -> None:
        super().__init__(data, blind_id, entry_id)
        self._attr_name = "Battery"
        self._attr_unique_id = f"{entry_id}_battery_{blind_id}"
        self._warned = False

    @property
    def native_value(self) -> int | None:
        voltage = self._voltage
        if voltage is None:
            return None
        value = battery_percent(
            voltage, self._data.battery_min_voltage, self._data.battery_max_voltage
        )
        if value is None and not self._warned:
            self._warned = True
            _LOGGER.warning(
                "Blind %s reports %.2f V, which doesn't match a known battery type. "
                "Set the battery voltage range in the integration options",
                self._blind_id,
                voltage,
            )
        return value


class PulseProVoltage(_PulseProVoltageBase):
    """Raw battery voltage (diagnostic), so the percentage can be checked."""

    _attr_device_class = SensorDeviceClass.VOLTAGE
    _attr_native_unit_of_measurement = UnitOfElectricPotential.VOLT
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_suggested_display_precision = 2

    def __init__(self, data: PulseProData, blind_id: str, entry_id: str) -> None:
        super().__init__(data, blind_id, entry_id)
        self._attr_name = "Battery voltage"
        self._attr_unique_id = f"{entry_id}_voltage_{blind_id}"

    @property
    def native_value(self) -> float | None:
        return self._voltage
