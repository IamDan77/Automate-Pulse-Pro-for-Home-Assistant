"""Position, battery, signal and hub sensors for Automate Pulse PRO."""
from __future__ import annotations

import logging

from datetime import datetime

from homeassistant.components.sensor import (
    RestoreSensor,
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.const import (
    PERCENTAGE,
    SIGNAL_STRENGTH_DECIBELS_MILLIWATT,
    EntityCategory,
    UnitOfElectricPotential,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import BATTERY_PROFILES, DOMAIN, HUB_LISTENER
from .entity import PulseProEntity, PulseProStatusEntity
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
        if data.use_websocket:
            entities.append(PulseProSignal(data, blind_id, entry.entry_id))
    entities.append(PulseProLastReport(data, entry.entry_id))
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


class PulseProSignal(PulseProStatusEntity, SensorEntity):
    """Radio signal strength between the hub and the blind (diagnostic).

    Comes from the hub's WebSocket. It is the hub's last reading, which is only
    updated when the motor's reply reaches the hub.
    """

    _attr_device_class = SensorDeviceClass.SIGNAL_STRENGTH
    _attr_native_unit_of_measurement = SIGNAL_STRENGTH_DECIBELS_MILLIWATT
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, data: PulseProData, blind_id: str, entry_id: str) -> None:
        super().__init__(data, blind_id, entry_id)
        self._attr_name = "Signal strength"
        self._attr_unique_id = f"{entry_id}_signal_{blind_id}"

    @property
    def available(self) -> bool:
        return self._has_status(self._hub.signal)

    @property
    def native_value(self) -> int | None:
        return self._hub.signal.get(self._blind_id)


class PulseProLastReport(RestoreSensor):
    """When a motor's own reply last reached the hub (diagnostic, on the hub).

    Position reports and command confirmations count; battery replies don't,
    because the hub answers those from memory. If this stops changing while
    the blinds are used, the hub is no longer hearing the motors.
    """

    _attr_should_poll = False
    _attr_has_entity_name = True
    _attr_device_class = SensorDeviceClass.TIMESTAMP
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_icon = "mdi:radio-tower"

    def __init__(self, data: PulseProData, entry_id: str) -> None:
        self._hub = data.hub
        self._attr_name = "Last blind report"
        self._attr_unique_id = f"{entry_id}_hub_last_report"
        self._attr_device_info = DeviceInfo(identifiers={(DOMAIN, data.hub_identifier)})

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        if self._hub.last_motor_report is None:
            last = await self.async_get_last_sensor_data()
            if last is not None and isinstance(last.native_value, datetime):
                self._hub.last_motor_report = last.native_value
        self.async_on_remove(self._hub.add_listener(HUB_LISTENER, self._handle_update))

    @callback
    def _handle_update(self) -> None:
        self.async_write_ha_state()

    @property
    def native_value(self) -> datetime | None:
        return self._hub.last_motor_report
