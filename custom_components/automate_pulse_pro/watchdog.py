"""Restart the Pulse hub with a smart plug when it stops hearing the blinds.

Some hubs (seen on a Pulse PRO with firmware 1.3.0) stop receiving the
motors' replies after a few hours. Commands still go out, but positions and
battery values stop updating until the hub is power cycled. The hub offers no
software restart, so a smart plug is switched off and on.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta

from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.event import async_track_time_interval
from homeassistant.util import dt as dt_util

from .const import (
    EVENT_HUB_RESTARTED,
    RESTART_CHECK_INTERVAL,
    RESTART_GIVE_UP,
    RESTART_LOCKOUT,
    RESTART_OFF_TIME,
)
from .hub import PulseProHub

_LOGGER = logging.getLogger(__name__)


class HubWatchdog:
    """Power cycles the hub when no blind has reported for a while."""

    def __init__(
        self,
        hass: HomeAssistant,
        hub: PulseProHub,
        switch_entity: str,
        after_minutes: int,
        position_interval: int,
    ) -> None:
        self._hass = hass
        self._hub = hub
        self.switch_entity = switch_entity
        # Blinds report at most once per position check, so wait for at least
        # three checks before calling the hub stuck
        self.threshold = timedelta(
            seconds=max(after_minutes * 60, 3 * position_interval)
        )
        self._started = dt_util.utcnow()
        self.last_restart: datetime | None = None
        self._restarting = False
        self._gave_up = False
        self._unsub = None

    def start(self) -> None:
        self._unsub = async_track_time_interval(
            self._hass, self._async_check, timedelta(seconds=RESTART_CHECK_INTERVAL)
        )

    @callback
    def stop(self) -> None:
        if self._unsub is not None:
            self._unsub()
            self._unsub = None

    async def _async_check(self, now: datetime | None = None) -> None:
        now = now or dt_util.utcnow()
        if self._restarting:
            return
        last = self._hub.last_motor_report
        if last is None:
            # No blind has ever reported on this hub, so a missing report
            # doesn't mean anything is wrong
            return
        if now - last >= timedelta(seconds=RESTART_GIVE_UP):
            if not self._gave_up:
                self._gave_up = True
                _LOGGER.warning(
                    "No blind on the Pulse PRO hub at %s has reported for over %s "
                    "hours. Automatic restarts are paused until a blind reports again",
                    self._hub.host,
                    RESTART_GIVE_UP // 3600,
                )
            return
        self._gave_up = False
        # Count from start-up and from the last restart too, so the hub gets
        # time to come back before anything else happens
        since = max(last, self._started, self.last_restart or self._started)
        if now - since < self.threshold:
            return
        if self.last_restart is not None and now - self.last_restart < timedelta(
            seconds=RESTART_LOCKOUT
        ):
            return
        _LOGGER.warning(
            "No blind on the Pulse PRO hub at %s has reported for %s minutes (last "
            "report %s). Restarting the hub with %s",
            self._hub.host,
            int((now - last).total_seconds() // 60),
            dt_util.as_local(last).strftime("%Y-%m-%d %H:%M"),
            self.switch_entity,
        )
        try:
            await self.async_restart("automatic")
        except HomeAssistantError:
            pass  # already logged

    async def async_restart(self, reason: str) -> None:
        """Switch the plug off, wait, and switch it on again."""
        if self._restarting:
            raise HomeAssistantError("The hub is already being restarted")
        self._restarting = True
        self.last_restart = dt_util.utcnow()
        failed: HomeAssistantError | None = None
        try:
            await self._switch("turn_off")
            await asyncio.sleep(RESTART_OFF_TIME)
        except HomeAssistantError as err:
            failed = err
            _LOGGER.error(
                "Could not switch off %s to restart the Pulse PRO hub: %s",
                self.switch_entity,
                err,
            )
        finally:
            # Never leave the hub without power, whatever happened above
            try:
                await self._switch("turn_on")
            except HomeAssistantError as err:
                _LOGGER.error(
                    "Could not switch %s back on. The Pulse PRO hub may have no "
                    "power: %s",
                    self.switch_entity,
                    err,
                )
            self._restarting = False
        if failed is not None:
            raise failed
        _LOGGER.warning(
            "Pulse PRO hub at %s was power cycled (%s)", self._hub.host, reason
        )
        self._hass.bus.async_fire(
            EVENT_HUB_RESTARTED,
            {"host": self._hub.host, "reason": reason, "switch": self.switch_entity},
        )

    async def _switch(self, service: str) -> None:
        try:
            await self._hass.services.async_call(
                "switch", service, {"entity_id": self.switch_entity}, blocking=True
            )
        except HomeAssistantError:
            raise
        except Exception as err:  # noqa: BLE001 - report every failure the same way
            raise HomeAssistantError(str(err)) from err
