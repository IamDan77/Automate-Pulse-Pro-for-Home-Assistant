import socket
import re
from homeassistant.components.cover import CoverEntity, CoverEntityFeature, ATTR_POSITION
from .const import DOMAIN

async def async_setup_entry(hass, config_entry, async_add_entities):
    """Set up covers from config entry."""
    data = hass.data[DOMAIN][config_entry.entry_id]
    entities = [
        PulseProCover(blind_id, data["host"], data["port"], config_entry.entry_id)
        for blind_id in data["blinds"]
    ]
    async_add_entities(entities, True)

class PulseProCover(CoverEntity):
    """Pulse PRO Cover item linked directly to Device Registry."""

    def __init__(self, blind_id, host, port, entry_id):
        self._blind_id = blind_id.upper()
        self._host = host
        self._port = port
        self._entry_id = entry_id
        self._current_position = None
        
        self._attr_name = f"Pulse Blind {self._blind_id}"
        self._attr_unique_id = f"{entry_id}_cover_{self._blind_id}"
        self._attr_supported_features = (
            CoverEntityFeature.OPEN | CoverEntityFeature.CLOSE | 
            CoverEntityFeature.STOP | CoverEntityFeature.SET_POSITION
        )

    @property
    def current_cover_position(self): return self._current_position
    @property
    def is_closed(self): return self._current_position == 0 if self._current_position is not None else None

    @property
    def device_info(self):
        """CRITICAL: The shared unique identifier linking cover and sensor."""
        return {
            "identifiers": {(DOMAIN, self._blind_id)},
            "name": f"Automate Shade {self._blind_id}",
            "manufacturer": "Rollease Acmeda",
            "model": "Pulse PRO Controlled Shade",
        }

    def _send(self, action, read=False):
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.settimeout(2.0)
                s.connect((self._host, self._port))
                s.sendall(f"!{self._blind_id}{action};\n".encode('ascii'))
                if read: return s.recv(1024).decode('ascii')
        except Exception: pass
        return ""

    def update(self):
        res = self._send("r?", read=True)
        match = re.search(rf"!{self._blind_id}r(\d+)", res) if res else None
        if match: self._current_position = max(0, min(100, int(match.group(1))))

    def open_cover(self, **kwargs): self._send("o"); self._current_position = 100; self.schedule_update_ha_state()
    def close_cover(self, **kwargs): self._send("c"); self._current_position = 0; self.schedule_update_ha_state()
    def stop_cover(self, **kwargs): self._send("s")
    def set_cover_position(self, **kwargs):
        if ATTR_POSITION in kwargs:
            pos = kwargs[ATTR_POSITION]
            self._send(f"m{max(0, min(99, int(pos))):02d}")
            self._current_position = pos
            self.schedule_update_ha_state()