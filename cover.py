"""Cover platform for Automate Pulse PRO blinds."""
from __future__ import annotations

from typing import Any

from homeassistant.components.cover import ATTR_POSITION, CoverEntity, CoverEntityFeature
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import ACTION_CLOSE, ACTION_OPEN, ACTION_STOP
from .entity import PulseProEntity
from .hub import HubError
from .models import PulseProConfigEntry, PulseProData


async def async_setup_entry(
    hass: HomeAssistant,
    entry: PulseProConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    data = entry.runtime_data
    async_add_entities(PulseProCover(data, b, entry.entry_id) for b in data.blinds)


class PulseProCover(PulseProEntity, CoverEntity):
    """A blind controlled by the Pulse PRO hub."""

    _attr_supported_features = (
        CoverEntityFeature.OPEN
        | CoverEntityFeature.CLOSE
        | CoverEntityFeature.STOP
        | CoverEntityFeature.SET_POSITION
    )

    def __init__(self, data: PulseProData, blind_id: str, entry_id: str) -> None:
        super().__init__(data, blind_id, entry_id)
        # The cover is the main entity, so it takes the device name.
        # Same unique ID as v1, so existing entities and history are kept.
        self._attr_name = None
        self._attr_unique_id = f"{entry_id}_cover_{blind_id}"

    @property
    def current_cover_position(self) -> int | None:
        # None (unknown) until the blind has reported - no made-up start value
        return self._hub.positions.get(self._blind_id)

    @property
    def is_closed(self) -> bool | None:
        position = self.current_cover_position
        return None if position is None else position == 0

    async def async_open_cover(self, **kwargs: Any) -> None:
        await self._command(ACTION_OPEN, 100)

    async def async_close_cover(self, **kwargs: Any) -> None:
        await self._command(ACTION_CLOSE, 0)

    async def async_stop_cover(self, **kwargs: Any) -> None:
        await self._command(ACTION_STOP, None)

    async def async_set_cover_position(self, **kwargs: Any) -> None:
        position = max(0, min(100, int(kwargs[ATTR_POSITION])))
        try:
            await self._hub.async_move(self._blind_id, position)
        except HubError as err:
            raise HomeAssistantError(
                f"Could not send command to blind {self._blind_id}: {err}"
            ) from err
        self._hub.set_position(self._blind_id, position)

    async def _command(self, action: str, optimistic: int | None) -> None:
        try:
            await self._hub.async_command(self._blind_id, action)
        except HubError as err:
            raise HomeAssistantError(
                f"Could not send command to blind {self._blind_id}: {err}"
            ) from err
        if optimistic is not None:
            self._hub.set_position(self._blind_id, optimistic)
