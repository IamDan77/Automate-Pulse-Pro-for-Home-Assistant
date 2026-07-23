import socket
import re
from homeassistant.components.sensor import SensorEntity, SensorDeviceClass
from homeassistant.const import PERCENTAGE
from .const import DOMAIN

async def async_setup_entry(hass, config_entry, async_add_entities):
    """Set up battery sensors from config entry."""
    data = hass.data[DOMAIN][config_entry.entry_id]
    entities = [
        PulseProBattery(blind_id, data["host"], data["port"], config_entry.entry_id)
        for blind_id in data["blinds"]
    ]
    async_add_entities(entities, True)

class PulseProBattery(SensorEntity):
    """Pulse PRO Battery item bound precisely to Device Registry matching cover."""

    def __init__(self, blind_id, host, port, entry_id):
        self._blind_id = blind_id.upper()
        self._host = host
        self._port = port
        self._attr_native_unit_of_measurement = PERCENTAGE
        self._attr_device_class = SensorDeviceClass.BATTERY
        self._attr_name = f"Pulse Blind {self._blind_id} Battery"
        self._attr_unique_id = f"{entry_id}_battery_{self._blind_id}"

    @property
    def device_info(self):
        """CRITICAL: Must exactly match device_info inside cover.py."""
        return {
            "identifiers": {(DOMAIN, self._blind_id)},
            "name": f"Automate Shade {self._blind_id}",
        }

    def update(self):
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.settimeout(2.0)
                s.connect((self._host, self._port))
                s.sendall(f"!{self._blind_id}pVc;\n".encode('ascii'))
                res = s.recv(1024).decode('ascii')
            match = re.search(rf"!{self._blind_id}pVc(\d+)", res) if res else None
            if match:
                v = int(match.group(1))
                v = v / 100 if v > 100 else v
                self._attr_native_value = max(0, min(100, int((v - 11.0) / (12.6 - 11.0) * 100)))
        except Exception: pass