"""Runtime data for the Automate Pulse PRO integration."""
from __future__ import annotations

from dataclasses import dataclass

from homeassistant.config_entries import ConfigEntry

from .hub import PulseProHub


@dataclass
class PulseProData:
    """Objects shared by the platforms of one config entry."""

    hub: PulseProHub
    blinds: list[str]
    battery_blinds: list[str]  # blinds with a battery (not mains powered)
    battery_min_voltage: float  # 0 = automatic
    battery_max_voltage: float  # 0 = automatic


type PulseProConfigEntry = ConfigEntry[PulseProData]
