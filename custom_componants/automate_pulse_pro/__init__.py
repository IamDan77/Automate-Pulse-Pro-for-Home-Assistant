import socket
import re
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from .const import DOMAIN

PLATFORMS = ["cover", "sensor"]

async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Automate Pulse PRO via UI config entry."""
    host = entry.data["host"]
    port = entry.data["port"]

# Reach out to the hub synchronously inside an executor block to grab blind lists
    def discover_blinds():
        blinds = []
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.settimeout(2.0)  # Total time to wait for the hub to speak
                s.connect((host, port))
                s.sendall(b"!000v;\n")
                
                # UPDATED: Loop and collect ALL data chunks until the stream stops
                reply = ""
                while True:
                    try:
                        chunk = s.recv(4096).decode('ascii')
                        if not chunk:
                            break
                        reply += chunk
                    except socket.timeout:
                        break  # Stop reading when the hub finishes talking
                
                # Parse all 3-character unique blind alphanumeric markers
                matches = re.findall(r"!([A-Z0-9]{3})v", reply)
                for blind_id in matches:
                    if blind_id != "BR1": # Filter out the Hub's controller ID
                        blinds.append(blind_id)
        except Exception:
            pass
        return blinds

    discovered_ids = await hass.async_add_executor_job(discover_blinds)
    
    # Store data in memory so cover.py and sensor.py can grab it instantly
    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN][entry.entry_id] = {
        "host": host,
        "port": port,
        "blinds": discovered_ids if discovered_ids else ["WSG"] # Fallback to your working code if hub is asleep
    }

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True

async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id)
    return unload_ok