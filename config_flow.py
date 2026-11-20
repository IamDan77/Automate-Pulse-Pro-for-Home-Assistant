"""Config and options flow for Automate Pulse PRO."""
from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.const import CONF_HOST, CONF_PORT
from homeassistant.core import callback

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
    DEFAULT_PORT,
    DEFAULT_POSITION_INTERVAL,
    DOMAIN,
    MAX_POSITION_INTERVAL,
    MIN_POSITION_INTERVAL,
)
from .hub import HubError, PulseProHub, parse_blind_ids

_LOGGER = logging.getLogger(__name__)

USER_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_HOST): str,
        vol.Required(CONF_PORT, default=DEFAULT_PORT): vol.All(
            vol.Coerce(int), vol.Range(min=1, max=65535)
        ),
    }
)


async def _async_test_hub(host: str, port: int) -> dict[str, Any]:
    """Connect, discover the blinds and return the entry data to store.

    Raises OSError, TimeoutError or HubError if the hub can't be used.
    """
    hub = PulseProHub(host, port)
    try:
        await hub.async_connect()
        blinds = await hub.async_discover()
        return {
            CONF_BLINDS: blinds,
            CONF_MAINS: sorted(a for a, t in hub.motor_types.items() if t == "A"),
            CONF_NAMES: dict(hub.names),
        }
    finally:
        await hub.async_stop()


class PulseProConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Automate Pulse PRO."""

    VERSION = 1

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        return PulseProOptionsFlow()

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            host = user_input[CONF_HOST].strip()
            port = user_input[CONF_PORT]

            # Stop the same hub being added twice (also catches v1 entries)
            self._async_abort_entries_match({CONF_HOST: host})
            await self.async_set_unique_id(host.lower())
            self._abort_if_unique_id_configured()

            try:
                found = await _async_test_hub(host, port)
            except (OSError, TimeoutError, HubError):
                errors["base"] = "cannot_connect"
            except Exception:  # noqa: BLE001
                _LOGGER.exception("Unexpected error while testing the Pulse PRO hub")
                errors["base"] = "unknown"
            else:
                return self.async_create_entry(
                    title=f"Pulse PRO ({host})",
                    data={CONF_HOST: host, CONF_PORT: port, **found},
                )

        return self.async_show_form(
            step_id="user",
            data_schema=self.add_suggested_values_to_schema(USER_SCHEMA, user_input),
            errors=errors,
        )

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Change the hub's IP address or port without losing any blinds."""
        entry = self._get_reconfigure_entry()
        errors: dict[str, str] = {}
        if user_input is not None:
            host = user_input[CONF_HOST].strip()
            port = user_input[CONF_PORT]
            if host.lower() != entry.data[CONF_HOST].lower():
                self._async_abort_entries_match({CONF_HOST: host})

            try:
                found = await _async_test_hub(host, port)
            except (OSError, TimeoutError, HubError):
                errors["base"] = "cannot_connect"
            except Exception:  # noqa: BLE001
                _LOGGER.exception("Unexpected error while testing the Pulse PRO hub")
                errors["base"] = "unknown"
            else:
                # Keep the blinds found before and add any new ones
                blinds = sorted({*entry.data.get(CONF_BLINDS, []), *found[CONF_BLINDS]})
                return self.async_update_reload_and_abort(
                    entry,
                    unique_id=host.lower(),
                    title=f"Pulse PRO ({host})",
                    data={
                        **entry.data,
                        CONF_HOST: host,
                        CONF_PORT: port,
                        CONF_BLINDS: blinds,
                        CONF_NAMES: {**entry.data.get(CONF_NAMES, {}), **found[CONF_NAMES]},
                    },
                )

        current = user_input or {
            CONF_HOST: entry.data[CONF_HOST],
            CONF_PORT: entry.data[CONF_PORT],
        }
        return self.async_show_form(
            step_id="reconfigure",
            data_schema=self.add_suggested_values_to_schema(USER_SCHEMA, current),
            errors=errors,
        )


class PulseProOptionsFlow(OptionsFlow):
    """Options: extra/ignored blinds, poll interval, direction and battery range."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            extra, bad_extra = parse_blind_ids(user_input.get(CONF_EXTRA_BLINDS, ""))
            excluded, bad_excluded = parse_blind_ids(
                user_input.get(CONF_EXCLUDED_BLINDS, "")
            )
            if bad_extra:
                errors[CONF_EXTRA_BLINDS] = "invalid_blind_id"
            if bad_excluded:
                errors[CONF_EXCLUDED_BLINDS] = "invalid_blind_id"

            vmin = float(user_input.get(CONF_BATTERY_MIN_V, 0) or 0)
            vmax = float(user_input.get(CONF_BATTERY_MAX_V, 0) or 0)
            if (vmin or vmax) and not (vmin and vmax and vmin < vmax):
                errors["base"] = "invalid_voltage_range"

            if not errors:
                return self.async_create_entry(
                    data={
                        CONF_EXTRA_BLINDS: ", ".join(extra),
                        CONF_EXCLUDED_BLINDS: ", ".join(excluded),
                        CONF_POSITION_INTERVAL: user_input[CONF_POSITION_INTERVAL],
                        CONF_INVERT_POSITION: bool(
                            user_input.get(CONF_INVERT_POSITION, False)
                        ),
                        CONF_BATTERY_MIN_V: vmin,
                        CONF_BATTERY_MAX_V: vmax,
                    }
                )

        current = {**self.config_entry.options, **(user_input or {})}
        schema = vol.Schema(
            {
                vol.Optional(
                    CONF_EXTRA_BLINDS, default=current.get(CONF_EXTRA_BLINDS, "")
                ): str,
                vol.Optional(
                    CONF_EXCLUDED_BLINDS, default=current.get(CONF_EXCLUDED_BLINDS, "")
                ): str,
                vol.Required(
                    CONF_POSITION_INTERVAL,
                    default=current.get(CONF_POSITION_INTERVAL, DEFAULT_POSITION_INTERVAL),
                ): vol.All(
                    vol.Coerce(int),
                    vol.Range(min=MIN_POSITION_INTERVAL, max=MAX_POSITION_INTERVAL),
                ),
                vol.Required(
                    CONF_INVERT_POSITION,
                    default=current.get(CONF_INVERT_POSITION, False),
                ): bool,
                vol.Required(
                    CONF_BATTERY_MIN_V, default=current.get(CONF_BATTERY_MIN_V, 0.0)
                ): vol.All(vol.Coerce(float), vol.Range(min=0, max=30)),
                vol.Required(
                    CONF_BATTERY_MAX_V, default=current.get(CONF_BATTERY_MAX_V, 0.0)
                ): vol.All(vol.Coerce(float), vol.Range(min=0, max=30)),
            }
        )
        data = self.config_entry.data
        names = data.get(CONF_NAMES, {})
        known = [
            f"{b} ({names[b]})" if b in names else b for b in data.get(CONF_BLINDS, [])
        ]
        return self.async_show_form(
            step_id="init",
            data_schema=schema,
            errors=errors,
            description_placeholders={"blinds": ", ".join(known) or "none yet"},
        )
