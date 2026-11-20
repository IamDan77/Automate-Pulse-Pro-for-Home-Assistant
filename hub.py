"""Async client for the Rollease Acmeda Automate Pulse PRO hub.

One long-lived TCP connection is shared by every entity. The hub replies (and
may push updates) as ASCII messages such as ``!ABCr050b180;``. Every message is
parsed here and the matching entities are told to refresh.

This module has no Home Assistant imports, so it can be tested on its own.
"""
from __future__ import annotations

import asyncio
import contextlib
import logging
import re
import socket
import time
from collections.abc import Callable, Iterable

from .const import (
    ACTION_CLOSE,
    ACTION_MOVE,
    ACTION_OPEN,
    ACTION_QUERY_NAME,
    ACTION_QUERY_POSITION,
    ACTION_QUERY_VOLTAGE,
    BATTERY_INTERVAL,
    CMD_DISCOVER,
    COMMAND_GAP,
    CONNECT_TIMEOUT,
    DEFAULT_POSITION_INTERVAL,
    DISCOVERY_MAX,
    DISCOVERY_QUIET,
    FOLLOW_UP_DELAYS,
    NAME_TIMEOUT,
    PROBE_MAX,
    PROBE_PER_BLIND,
    PROBE_QUIET,
    PROBE_SETTLE,
    PROBE_TIMEOUT,
    RECONNECT_MAX_DELAY,
    RECONNECT_MIN_DELAY,
    REQUEST_TIMEOUT,
    SILENT_ROUNDS_BEFORE_RECONNECT,
)

_LOGGER = logging.getLogger(__name__)

BLIND_ID_RE = re.compile(r"^[A-Z0-9]{3}$")
POSITION_RE = re.compile(r"^r(\d{1,3})")
VOLTAGE_RE = re.compile(r"^pVc(\d+)")
NAME_RE = re.compile(r"^NAME(.*)$")
MESSAGE_RE = re.compile(r"!([A-Za-z0-9]{3})([^!]*)$")

Listener = Callable[[], None]


class HubError(Exception):
    """Base error for hub communication."""


class HubNotConnected(HubError):
    """Raised when a command is sent while the hub is not connected."""


def parse_blind_ids(value: str | Iterable[str] | None) -> tuple[list[str], list[str]]:
    """Split a comma/space separated list into (valid IDs, invalid entries)."""
    if not value:
        return [], []
    items = re.split(r"[,\s;]+", value) if isinstance(value, str) else list(value)
    valid: list[str] = []
    invalid: list[str] = []
    for item in items:
        item = str(item).strip().upper()
        if not item:
            continue
        if BLIND_ID_RE.match(item):
            if item not in valid:
                valid.append(item)
        else:
            invalid.append(item)
    return valid, invalid


def parse_voltage(raw: str) -> float:
    """Convert the hub's voltage digits to volts (e.g. ``01180`` -> 11.8)."""
    value = int(raw)
    if value >= 1000:
        return value / 100  # centivolts
    if value >= 100:
        return value / 10  # decivolts
    return float(value)


def _enable_keepalive(writer: asyncio.StreamWriter) -> None:
    """Let the OS notice a dead connection (hub rebooted or dropped off Wi-Fi)."""
    sock = writer.get_extra_info("socket")
    if sock is None:
        return
    with contextlib.suppress(OSError):
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)
        for name, value in (("TCP_KEEPIDLE", 30), ("TCP_KEEPINTVL", 10), ("TCP_KEEPCNT", 3)):
            if hasattr(socket, name):
                sock.setsockopt(socket.IPPROTO_TCP, getattr(socket, name), value)


def _matcher(addr: str, pattern: re.Pattern[str]) -> Callable[[str, str], bool]:
    return lambda a, body: a == addr and pattern.match(body) is not None


class PulseProHub:
    """Connection to one Pulse PRO hub."""

    def __init__(self, host: str, port: int, invert_position: bool = False) -> None:
        self.host = host
        self.port = port
        # Some motors report 0 = open instead of 0 = closed. Positions are
        # always stored the Home Assistant way: 0 = closed, 100 = open.
        self.invert_position = invert_position
        self.positions: dict[str, int] = {}
        # Motor type from the version reply: "D" = DC (battery), "A" = AC (mains)
        self.motor_types: dict[str, str] = {}
        self.names: dict[str, str] = {}  # names set in the Automate app
        # IDs that answered the version query but are not motors (the hub itself)
        self.non_motor_ids: list[str] = []
        self.voltages: dict[str, float] = {}
        self.last_seen: dict[str, float] = {}

        self._reader: asyncio.StreamReader | None = None
        self._writer: asyncio.StreamWriter | None = None
        self._write_lock = asyncio.Lock()
        self._closing = False
        self._read_task: asyncio.Task | None = None
        self._reconnect_task: asyncio.Task | None = None
        self._poll_task: asyncio.Task | None = None
        self._follow_ups: dict[str, asyncio.Task] = {}
        self._tasks: set[asyncio.Task] = set()
        self._listeners: dict[str, list[Listener]] = {}
        self._waiters: list[tuple[Callable[[str, str], bool], asyncio.Future]] = []
        self._version_ids: set[str] = set()
        self._blind_ids: list[str] = []
        self._battery_ids: list[str] = []
        self._position_interval = DEFAULT_POSITION_INTERVAL
        self._rx_count = 0  # all messages received (debug only)
        # Position/battery replies from our blinds. Used to spot a connection
        # that is open but no longer relays blind replies. Other messages (for
        # example from the hub itself) must not count, or a half-dead
        # connection is never noticed and blinds stay unavailable.
        self._blind_rx_count = 0

    # ------------------------------------------------------------------ state
    @property
    def connected(self) -> bool:
        """Return True while the TCP connection is open."""
        return self._writer is not None and not self._writer.is_closing()

    def is_blind_available(self, addr: str) -> bool:
        """Available = hub connected and the blind has answered recently."""
        if not self.connected:
            return False
        seen = self.last_seen.get(addr)
        if seen is None:
            return False
        return time.monotonic() - seen < self._position_interval * 3 + 30

    def _to_ha_position(self, raw: int) -> int:
        """Hub position -> Home Assistant position (0 = closed, 100 = open)."""
        position = max(0, min(100, raw))
        if self.invert_position:
            position = 100 - position
        # The hub reports 00-99, so treat the last step as fully open/closed
        if position <= 1:
            return 0
        if position >= 99:
            return 100
        return position

    def set_position(self, addr: str, position: int) -> None:
        """Store an optimistic position (corrected by the follow-up reads)."""
        self.positions[addr] = max(0, min(100, int(position)))
        self._notify(addr)

    # -------------------------------------------------------------- listeners
    def add_listener(self, addr: str, listener: Listener) -> Callable[[], None]:
        """Call ``listener`` when data for ``addr`` or the connection changes."""
        self._listeners.setdefault(addr, []).append(listener)

        def remove() -> None:
            with contextlib.suppress(KeyError, ValueError):
                self._listeners[addr].remove(listener)

        return remove

    def _notify(self, addr: str | None = None) -> None:
        if addr is None:
            targets = [cb for cbs in self._listeners.values() for cb in cbs]
        else:
            targets = list(self._listeners.get(addr, []))
        for listener in targets:
            try:
                listener()
            except Exception:  # noqa: BLE001 - one entity must not break the hub
                _LOGGER.exception("Error in Pulse PRO listener")

    # ------------------------------------------------------------- connection
    async def async_connect(self) -> None:
        """Open the connection. Raises OSError/TimeoutError on failure."""
        reader, writer = await asyncio.wait_for(
            asyncio.open_connection(self.host, self.port), CONNECT_TIMEOUT
        )
        _enable_keepalive(writer)
        self._reader, self._writer = reader, writer
        self._read_task = asyncio.create_task(
            self._read_loop(reader), name=f"pulse_pro_read_{self.host}"
        )
        _LOGGER.debug("Connected to Pulse PRO hub at %s:%s", self.host, self.port)
        self._notify()

    async def async_stop(self) -> None:
        """Close the connection and stop all background work."""
        self._closing = True
        tasks = [
            t
            for t in (
                self._poll_task,
                self._reconnect_task,
                self._read_task,
                *self._follow_ups.values(),
                *self._tasks,
            )
            if t is not None and not t.done()
        ]
        for task in tasks:
            task.cancel()
        for task in tasks:
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await task
        self._follow_ups.clear()
        self._tasks.clear()
        writer = self._writer
        self._drop_connection()
        if writer is not None:
            with contextlib.suppress(Exception):
                await asyncio.wait_for(writer.wait_closed(), 2)

    def _drop_connection(self, reader: asyncio.StreamReader | None = None) -> None:
        # Ignore read loops left over from an earlier connection
        if reader is not None and reader is not self._reader:
            return
        had_connection = self._writer is not None
        if self._writer is not None:
            with contextlib.suppress(Exception):
                self._writer.close()
        self._writer = None
        self._reader = None
        for _, fut in self._waiters:
            if not fut.done():
                fut.set_result(None)  # pending requests get "no reply"
        self._waiters.clear()
        if had_connection:
            self._notify()

    def _force_reconnect(self) -> None:
        """Drop a connection that is open but no longer answering, and reconnect."""
        read_task = self._read_task
        self._drop_connection()
        if read_task is not None and not read_task.done():
            read_task.cancel()
        self._schedule_reconnect()

    def _schedule_reconnect(self) -> None:
        if self._closing:
            return
        if self._reconnect_task is not None and not self._reconnect_task.done():
            return
        self._reconnect_task = asyncio.create_task(
            self._reconnect_loop(), name=f"pulse_pro_reconnect_{self.host}"
        )

    async def _reconnect_loop(self) -> None:
        delay = RECONNECT_MIN_DELAY
        while not self._closing and not self.connected:
            await asyncio.sleep(delay)
            if self._closing:
                return
            try:
                await self.async_connect()
            except (OSError, TimeoutError) as err:
                _LOGGER.debug("Reconnect to %s failed: %s", self.host, err)
                delay = min(delay * 2, RECONNECT_MAX_DELAY)
                continue
            except Exception:  # noqa: BLE001 - never let the reconnect loop die
                _LOGGER.exception("Unexpected error reconnecting to %s", self.host)
                delay = min(delay * 2, RECONNECT_MAX_DELAY)
                continue
            _LOGGER.warning("Reconnected to Pulse PRO hub at %s", self.host)
            self._spawn(self.async_refresh_all())

    def _spawn(self, coro) -> None:
        task = asyncio.create_task(coro)
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def _read_loop(self, reader: asyncio.StreamReader) -> None:
        buffer = ""
        try:
            while True:
                data = await reader.read(4096)
                if not data:
                    if not self._closing:
                        _LOGGER.warning("Pulse PRO hub at %s closed the connection", self.host)
                    break
                buffer += data.decode("ascii", errors="ignore")
                while ";" in buffer:
                    message, buffer = buffer.split(";", 1)
                    self._handle_message(message.strip())
                if len(buffer) > 4096:  # junk with no terminators
                    buffer = ""
        except asyncio.CancelledError:
            self._drop_connection(reader)
            raise
        except (OSError, ConnectionError) as err:
            if not self._closing:
                _LOGGER.warning("Lost connection to Pulse PRO hub at %s: %s", self.host, err)
        current = reader is self._reader
        self._drop_connection(reader)
        if current:
            self._schedule_reconnect()

    def _handle_message(self, message: str) -> None:
        # Replies can carry extra leading characters, e.g. "!!KCPpVc01038,R62",
        # so use the last "!" followed by a 3-character ID.
        match = MESSAGE_RE.search(message)
        if match is None:
            return
        addr = match.group(1).upper()
        body = match.group(2)
        self._rx_count += 1
        _LOGGER.debug("<- !%s%s", addr, body)

        changed = False
        if body.startswith("v"):
            self._version_ids.add(addr)
            # "vD.." = DC (battery) motor, "vA.." = AC (mains) motor
            if len(body) > 1 and body[1] in "AD":
                self.motor_types[addr] = body[1]
        elif (match := NAME_RE.match(body)):
            name = match.group(1).strip()
            if name:
                self.names[addr] = name
        elif (match := POSITION_RE.match(body)):
            self.positions[addr] = self._to_ha_position(int(match.group(1)))
            self.last_seen[addr] = time.monotonic()
            changed = True
        elif (match := VOLTAGE_RE.match(body)):
            self.voltages[addr] = parse_voltage(match.group(1))
            self.last_seen[addr] = time.monotonic()
            changed = True

        for predicate, fut in list(self._waiters):
            if not fut.done() and predicate(addr, body):
                fut.set_result(body)
        if changed:
            self._blind_rx_count += 1
            self._notify(addr)

    # -------------------------------------------------------------- commands
    async def async_send(self, command: str) -> None:
        """Send a raw command such as ``!ABCo;``."""
        async with self._write_lock:
            writer = self._writer
            if writer is None or writer.is_closing():
                raise HubNotConnected(f"Not connected to Pulse PRO hub at {self.host}")
            _LOGGER.debug("-> %s", command)
            try:
                writer.write(f"{command}\n".encode("ascii"))
                await asyncio.wait_for(writer.drain(), REQUEST_TIMEOUT)
            except (OSError, TimeoutError) as err:
                self._drop_connection()
                self._schedule_reconnect()
                raise HubNotConnected(str(err)) from err
            await asyncio.sleep(COMMAND_GAP)

    async def async_request(
        self,
        command: str,
        predicate: Callable[[str, str], bool],
        timeout: float = REQUEST_TIMEOUT,
    ) -> str | None:
        """Send a command and wait for a matching reply. None = no reply."""
        fut = asyncio.get_running_loop().create_future()
        waiter = (predicate, fut)
        self._waiters.append(waiter)
        try:
            await self.async_send(command)
            return await asyncio.wait_for(fut, timeout)
        except TimeoutError:
            return None
        finally:
            with contextlib.suppress(ValueError):
                self._waiters.remove(waiter)

    async def async_command(self, addr: str, action: str) -> None:
        """Send a movement command, then re-read the position a few times."""
        await self.async_send(f"!{addr}{action};")
        old = self._follow_ups.pop(addr, None)
        if old is not None:
            old.cancel()
        self._follow_ups[addr] = asyncio.create_task(self._follow_up(addr))

    async def async_move(self, addr: str, position: int) -> None:
        """Move to a Home Assistant position (0 = closed, 100 = open)."""
        position = max(0, min(100, int(position)))
        if position >= 100:
            action = ACTION_OPEN
        elif position <= 0:
            action = ACTION_CLOSE
        else:
            target = 100 - position if self.invert_position else position
            # The hub takes two digits (01-99) for a position
            action = f"{ACTION_MOVE}{max(1, min(99, target)):02d}"
        await self.async_command(addr, action)

    async def _follow_up(self, addr: str) -> None:
        elapsed = 0
        for at in FOLLOW_UP_DELAYS:
            await asyncio.sleep(at - elapsed)
            elapsed = at
            try:
                await self.async_query_position(addr)
            except HubError:
                return

    async def async_query_position(self, addr: str) -> int | None:
        reply = await self.async_request(
            f"!{addr}{ACTION_QUERY_POSITION};", _matcher(addr, POSITION_RE)
        )
        return None if reply is None else self.positions.get(addr)

    async def async_query_voltage(self, addr: str) -> float | None:
        reply = await self.async_request(
            f"!{addr}{ACTION_QUERY_VOLTAGE};", _matcher(addr, VOLTAGE_RE)
        )
        return None if reply is None else self.voltages.get(addr)

    # ------------------------------------------------------------- discovery
    async def async_discover(self) -> list[str]:
        """Return the IDs of the blinds paired with the hub.

        Every device that answers the version query is a candidate. Motors say
        what they are in that reply ("vD" = battery, "vA" = mains), which
        filters out the hub itself without hard-coding its ID. If no reply has
        a motor type, only devices that answer a position query count.
        The names set in the Automate app are read as well.
        """
        loop = asyncio.get_running_loop()
        self._version_ids.clear()
        self.non_motor_ids = []
        await self.async_send(CMD_DISCOVER)

        deadline = loop.time() + DISCOVERY_MAX
        count, last_change = 0, loop.time()
        while loop.time() < deadline:
            await asyncio.sleep(0.25)
            if len(self._version_ids) != count:
                count, last_change = len(self._version_ids), loop.time()
            elif loop.time() - last_change >= DISCOVERY_QUIET:
                break

        candidates = sorted(
            a for a in self._version_ids if BLIND_ID_RE.match(a) and a != "000"
        )
        if not candidates:
            return []

        motors = [a for a in candidates if a in self.motor_types]
        if motors:
            self.non_motor_ids = [a for a in candidates if a not in motors]
            if self.non_motor_ids:
                _LOGGER.info(
                    "Ignoring %s: not a motor (probably the hub itself)",
                    ", ".join(self.non_motor_ids),
                )
            await self._query_names(motors)
            return motors

        blinds = await self._probe_positions(candidates)
        if not blinds:
            _LOGGER.warning(
                "None of the devices reported by the Pulse PRO hub (%s) answered a "
                "position query, so all of them were added. If one of them is the "
                "hub itself, ignore it in the integration options",
                ", ".join(candidates),
            )
            await self._query_names(candidates)
            return candidates
        skipped = [a for a in candidates if a not in blinds]
        if skipped:
            _LOGGER.info(
                "Ignoring %s: no reply to a position query (probably the hub itself, "
                "or a blind that is asleep/out of range). Add it in the options if needed",
                ", ".join(skipped),
            )
        await self._query_names(blinds)
        return blinds

    async def _query_names(self, addrs: list[str]) -> None:
        """Ask the hub for the name of each blind. Missing names are fine."""
        loop = asyncio.get_running_loop()
        waiters = {a: (_matcher(a, NAME_RE), loop.create_future()) for a in addrs}
        self._waiters.extend(waiters.values())
        try:
            for addr in addrs:
                await self.async_send(f"!{addr}{ACTION_QUERY_NAME};")
            await asyncio.wait([fut for _, fut in waiters.values()], timeout=NAME_TIMEOUT)
        except HubError as err:
            _LOGGER.debug("Reading blind names failed: %s", err)
        finally:
            for waiter in waiters.values():
                with contextlib.suppress(ValueError):
                    self._waiters.remove(waiter)

    async def _probe_positions(self, addrs: list[str]) -> list[str]:
        """Return the IDs that answer a position query.

        The hub relays each query to its blind over RF one at a time, so with
        many blinds the replies trickle in. Wait long enough for all of them.
        If nobody answered at all (hub still busy), ask everyone once more.
        """
        # Let the hub finish answering the version query first
        await asyncio.sleep(PROBE_SETTLE)
        answered = await self._probe_once(addrs)
        if not answered and self.connected:
            _LOGGER.debug("No position replies yet, asking all blinds again")
            answered = await self._probe_once(addrs)
        return answered

    async def _probe_once(self, addrs: list[str]) -> list[str]:
        loop = asyncio.get_running_loop()
        waiters = {a: (_matcher(a, POSITION_RE), loop.create_future()) for a in addrs}
        self._waiters.extend(waiters.values())
        timeout = min(PROBE_MAX, PROBE_TIMEOUT + PROBE_PER_BLIND * len(addrs))
        try:
            for addr in addrs:
                await self.async_send(f"!{addr}{ACTION_QUERY_POSITION};")
            # Stop when every blind has answered, when replies have stopped
            # coming in for a while (the rest are probably the hub itself or
            # asleep), or at the overall time limit.
            futs = [fut for _, fut in waiters.values()]
            deadline = loop.time() + timeout
            done_count, last_change = 0, loop.time()
            while loop.time() < deadline:
                await asyncio.sleep(0.25)
                count = sum(fut.done() for fut in futs)
                if count == len(futs):
                    break
                if count != done_count:
                    done_count, last_change = count, loop.time()
                elif loop.time() - last_change >= max(PROBE_QUIET, PROBE_TIMEOUT if not count else 0):
                    break
        finally:
            for waiter in waiters.values():
                with contextlib.suppress(ValueError):
                    self._waiters.remove(waiter)
        return [
            a
            for a, (_, fut) in waiters.items()
            if fut.done() and not fut.cancelled() and fut.result() is not None
        ]

    # --------------------------------------------------------------- polling
    def start(
        self,
        blind_ids: Iterable[str],
        position_interval: int,
        battery_ids: Iterable[str] | None = None,
    ) -> None:
        """Start polling the given blinds in the background."""
        self._blind_ids = list(blind_ids)
        self._battery_ids = list(self._blind_ids if battery_ids is None else battery_ids)
        self._position_interval = position_interval
        self._poll_task = asyncio.create_task(
            self._poll_loop(), name=f"pulse_pro_poll_{self.host}"
        )

    async def async_refresh_positions(self) -> None:
        for addr in self._blind_ids:
            if not self.connected:
                return
            await self.async_query_position(addr)

    async def async_refresh_batteries(self) -> None:
        for addr in self._battery_ids:
            if not self.connected:
                return
            await self.async_query_voltage(addr)

    async def async_refresh_all(self) -> None:
        try:
            await self.async_refresh_positions()
            await self.async_refresh_batteries()
        except HubError as err:
            _LOGGER.debug("Refresh failed: %s", err)

    async def _poll_loop(self) -> None:
        last_battery: float | None = None
        silent_rounds = 0
        while not self._closing:
            try:
                if self.connected and self._blind_ids:
                    rx_before = self._blind_rx_count
                    await self.async_refresh_positions()
                    now = time.monotonic()
                    if last_battery is None or now - last_battery >= BATTERY_INTERVAL:
                        await self.async_refresh_batteries()
                        last_battery = now
                    # The connection looks open but nothing came back from any
                    # blind. This happens when the hub drops a client without
                    # closing the connection (e.g. after another app connects,
                    # or a Wi-Fi blip). Reconnect instead of waiting forever.
                    if self.connected and self._blind_rx_count == rx_before:
                        silent_rounds += 1
                        if silent_rounds >= SILENT_ROUNDS_BEFORE_RECONNECT:
                            _LOGGER.warning(
                                "No blind on the Pulse PRO hub at %s has answered for "
                                "%s polls; reconnecting",
                                self.host,
                                silent_rounds,
                            )
                            silent_rounds = 0
                            self._force_reconnect()
                    else:
                        silent_rounds = 0
            except HubError as err:
                _LOGGER.debug("Poll failed: %s", err)
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001 - never let polling stop for good
                _LOGGER.exception("Unexpected error polling Pulse PRO hub at %s", self.host)
            # Re-check availability so blinds that stopped answering go unavailable
            self._notify()
            await asyncio.sleep(self._position_interval)
