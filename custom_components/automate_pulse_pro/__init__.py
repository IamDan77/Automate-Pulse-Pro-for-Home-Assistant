"""The Automate Pulse PRO integration."""
from __future__ import annotations

import inspect
import logging

from homeassistant.const import CONF_HOST, CONF_PORT, Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers import device_registry as dr, entity_registry as er

from .const import (
    CONF_BATTERY_MAX_V,
    CONF_BATTERY_MIN_V,
    CONF_BLINDS,
    CONF_EXCLUDED_BLINDS,
    CONF_EXTRA_BLINDS,
    CONF_INVERT_POSITION,
    CONF_MAINS,
    CONF_NAMES,
    CONF_POSITION_INTERVAL,
    CONF_RESTART_AFTER,
    CONF_RESTART_SWITCH,
    CONF_USE_WEBSOCKET,
    DEFAULT_POSITION_INTERVAL,
    DEFAULT_RESTART_AFTER,
    DEFAULT_USE_WEBSOCKET,
    DOMAIN,
)
from .hub import HubError, PulseProHub, parse_blind_ids
from .watchdog import HubWatchdog
from .ws import PulseProWebSocket
from .models import PulseProConfigEntry, PulseProData

_LOGGER = logging.getLogger(__name__)

PLATFORMS = [Platform.BINARY_SENSOR, Platform.BUTTON, Platform.COVER, Platform.SENSOR]

# via_device_id was added in Home Assistant 2026.8 (via_device is deprecated
# from then on and stops working in 2027.8). Older versions only know via_device.
_HAS_VIA_DEVICE_ID = (
    "via_device_id" in inspect.signature(dr.DeviceRegistry.async_get_or_create).parameters
)


async def async_setup_entry(hass: HomeAssistant, entry: PulseProConfigEntry) -> bool:
    """Set up Automate Pulse PRO from a config entry."""
    host: str = entry.data[CONF_HOST]
    port: int = entry.data[CONF_PORT]
    options = entry.options
    hub = PulseProHub(
        host, port, reverse_position=bool(options.get(CONF_INVERT_POSITION, False))
    )

    try:
        await hub.async_connect()
    except (OSError, TimeoutError) as err:
        # Home Assistant retries automatically, with back-off
        raise ConfigEntryNotReady(
            f"Cannot connect to Pulse PRO hub at {host}:{port}: {err}"
        ) from err

    try:
        try:
            discovered = await hub.async_discover()
        except HubError as err:
            _LOGGER.warning("Blind discovery on %s failed: %s", host, err)
            discovered = []

        # Remember every blind found so far, so a blind that is asleep or out of
        # range at start-up keeps its entities (shown as unavailable).
        known, _ = parse_blind_ids(entry.data.get(CONF_BLINDS, []))
        new = [b for b in discovered if b not in known]
        if new:
            _LOGGER.info("Found new blinds on %s: %s", host, ", ".join(new))
        # Devices that turned out not to be motors (e.g. the hub itself, added
        # by older versions) are dropped
        if hub.non_motor_ids:
            _LOGGER.info(
                "Removing %s from the blinds: not a motor", ", ".join(hub.non_motor_ids)
            )
        known = sorted({*known, *new} - set(hub.non_motor_ids))

        mains = set(entry.data.get(CONF_MAINS, []))
        mains |= {a for a, t in hub.motor_types.items() if t == "A"}
        mains -= {a for a, t in hub.motor_types.items() if t == "D"}
        names = {**entry.data.get(CONF_NAMES, {}), **hub.names}
        new_data = {
            **entry.data,
            CONF_BLINDS: known,
            CONF_MAINS: sorted(mains),
            CONF_NAMES: names,
        }
        if new_data != dict(entry.data):
            hass.config_entries.async_update_entry(entry, data=new_data)

        extra, _ = parse_blind_ids(options.get(CONF_EXTRA_BLINDS, ""))
        excluded, _ = parse_blind_ids(options.get(CONF_EXCLUDED_BLINDS, ""))
        blinds = sorted({*known, *extra} - set(excluded))
        if not blinds:
            _LOGGER.warning(
                "No blinds found on the Pulse PRO hub at %s. Add your blinds in the "
                "Automate app and reload the integration, or enter their IDs in the "
                "integration options",
                host,
            )

        dev_reg = dr.async_get(hass)
        hub_device = dev_reg.async_get_or_create(
            config_entry_id=entry.entry_id,
            identifiers={(DOMAIN, f"hub_{entry.entry_id}")},
            manufacturer="Rollease Acmeda",
            model="Automate Pulse PRO",
            name=f"Pulse PRO hub ({host})",
        )
        # Create the blind devices here, linked to the hub by device ID
        # (via_device_id). Passing via_device in DeviceInfo is deprecated and
        # stops working in Home Assistant 2027.8.
        if _HAS_VIA_DEVICE_ID:
            link = {"via_device_id": hub_device.id}
        else:
            link = {"via_device": (DOMAIN, f"hub_{entry.entry_id}")}
        for blind_id in blinds:
            # Name from the Automate app if the hub reports one. A name you set
            # in Home Assistant always wins over this.
            dev_reg.async_get_or_create(
                config_entry_id=entry.entry_id,
                identifiers={(DOMAIN, blind_id)},
                manufacturer="Rollease Acmeda",
                model=(
                    "Pulse PRO Controlled Shade (mains)"
                    if blind_id in mains
                    else "Pulse PRO Controlled Shade"
                ),
                name=names.get(blind_id) or f"Automate Shade {blind_id}",
                serial_number=blind_id,
                **link,
            )
        battery_blinds = [b for b in blinds if b not in mains]
        use_websocket = bool(options.get(CONF_USE_WEBSOCKET, DEFAULT_USE_WEBSOCKET))
        restart_switch = options.get(CONF_RESTART_SWITCH) or None
        _remove_stale_entries(
            hass, entry, set(blinds), mains, use_websocket, restart_switch is not None
        )

        position_interval = options.get(CONF_POSITION_INTERVAL, DEFAULT_POSITION_INTERVAL)
        hub.start(
            blinds,
            position_interval,
            battery_blinds,
            PulseProWebSocket(host) if use_websocket else None,
        )
        watchdog = None
        if restart_switch is not None:
            watchdog = HubWatchdog(
                hass,
                hub,
                restart_switch,
                int(options.get(CONF_RESTART_AFTER, DEFAULT_RESTART_AFTER)),
                position_interval,
            )
        entry.runtime_data = PulseProData(
            hub=hub,
            hub_identifier=f"hub_{entry.entry_id}",
            blinds=blinds,
            battery_blinds=battery_blinds,
            use_websocket=use_websocket,
            watchdog=watchdog,
            battery_min_voltage=float(options.get(CONF_BATTERY_MIN_V, 0) or 0),
            battery_max_voltage=float(options.get(CONF_BATTERY_MAX_V, 0) or 0),
        )
        await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
        if watchdog is not None:
            watchdog.start()
            entry.async_on_unload(watchdog.stop)
            _LOGGER.info(
                "The Pulse PRO hub at %s is restarted with %s when no blind has "
                "reported for %s minutes",
                host,
                restart_switch,
                int(watchdog.threshold.total_seconds() // 60),
            )
    except Exception:
        await hub.async_stop()
        raise

    entry.async_on_unload(entry.add_update_listener(_async_options_updated))
    return True


async def async_unload_entry(hass: HomeAssistant, entry: PulseProConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        await entry.runtime_data.hub.async_stop()
    return unload_ok


async def _async_options_updated(hass: HomeAssistant, entry: PulseProConfigEntry) -> None:
    """Reload when the options change."""
    await hass.config_entries.async_reload(entry.entry_id)


def _remove_stale_entries(
    hass: HomeAssistant,
    entry: PulseProConfigEntry,
    blinds: set[str],
    mains: set[str],
    use_websocket: bool,
    has_restart_switch: bool,
) -> None:
    """Remove entities and devices for blinds that are ignored or gone.

    Battery entities of mains-powered blinds are removed as well, and the
    signal/online entities when the WebSocket is turned off.
    """
    battery_prefixes = (f"{entry.entry_id}_battery_", f"{entry.entry_id}_voltage_")
    ws_prefixes = (f"{entry.entry_id}_signal_", f"{entry.entry_id}_online_")
    hub_prefix = f"{entry.entry_id}_hub_"
    ent_reg = er.async_get(hass)
    for ent in er.async_entries_for_config_entry(ent_reg, entry.entry_id):
        if ent.unique_id.startswith(hub_prefix):
            # Entities of the hub itself. The restart button only exists
            # while a smart plug is set in the options.
            if ent.unique_id == f"{hub_prefix}restart" and not has_restart_switch:
                ent_reg.async_remove(ent.entity_id)
            continue
        # Unique IDs of blind entities end with the 3-character blind ID
        blind_id = ent.unique_id[-3:].upper()
        if (
            blind_id not in blinds
            or (blind_id in mains and ent.unique_id.startswith(battery_prefixes))
            or (not use_websocket and ent.unique_id.startswith(ws_prefixes))
        ):
            ent_reg.async_remove(ent.entity_id)

    dev_reg = dr.async_get(hass)
    for device in dr.async_entries_for_config_entry(dev_reg, entry.entry_id):
        for domain, ident in device.identifiers:
            if domain == DOMAIN and not ident.startswith("hub_") and ident not in blinds:
                dev_reg.async_update_device(device.id, remove_config_entry_id=entry.entry_id)
                break
