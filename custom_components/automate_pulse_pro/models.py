"""Runtime data for the Automate Pulse PRO integration."""
from __future__ import annotations

from dataclasses import dataclass

from homeassistant.config_entries import ConfigEntry

from .hub import PulseProHub
from .watchdog import HubWatchdog


@dataclass
class PulseProData:
    """Objects shared by the platforms of one config entry."""

    hub: PulseProHub
    hub_identifier: str  # device registry identifier of the hub device
    blinds: list[str]
    battery_blinds: list[str]  # blinds with a battery (not mains powered)
    use_websocket: bool  # signal strength and online status are read
    battery_min_voltage: float  # 0 = automatic
    battery_max_voltage: float  # 0 = automatic
    # Fields with a default value must come last in a dataclass
    watchdog: HubWatchdog | None = None  # restarts the hub with a smart plug


type PulseProConfigEntry = ConfigEntry[PulseProData]
