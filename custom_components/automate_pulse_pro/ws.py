"""Read-only client for the Pulse hub's WebSocket interface (wss://<hub>:443/rpc).

The Automate app uses this interface. This integration only uses it to read
the signal strength ("rs", dBm) and online status ("ol") of each blind, which
port 1487 doesn't provide. No commands are sent over it.

Standard library only. The hub's web server rejects requests with large
headers ("Header fields are too long"), so the handshake is kept minimal.
The hub's JSON is not always valid (on firmware 1.3.0 the last "}" is
missing), so replies are parsed leniently.
"""
from __future__ import annotations

import asyncio
import base64
import contextlib
import json
import os
import re
import ssl
import struct
import time
from typing import Any

from .const import WS_PATH, WS_PORT, WS_TIMEOUT

SHADE_RE = re.compile(r'"([A-Za-z0-9]{3})"\s*:\s*\{([^{}]*)\}')
FIELD_RE = r'"%s"\s*:\s*("[^"]*"|[^,}\s]+)'


class WebSocketError(Exception):
    """The hub's WebSocket could not be read."""


def _ssl_context() -> ssl.SSLContext:
    # The hub uses a self-signed certificate. No CA files are loaded, so this
    # doesn't block the event loop.
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    return ctx


def _to_int(value: Any) -> int | None:
    try:
        return int(str(value).strip('"'))
    except (TypeError, ValueError):
        return None


def _to_bool(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    text = str(value).strip('"').lower()
    if text in ("true", "1"):
        return True
    if text in ("false", "0"):
        return False
    return None


def parse_shades(text: str) -> dict[str, dict[str, Any]]:
    """Return {blind ID: {"rssi": dBm or None, "online": bool or None}}."""
    data = None
    for suffix in ("", "}", "}}"):
        try:
            data = json.loads(text + suffix)
            break
        except ValueError:
            continue
    result: dict[str, dict[str, Any]] = {}
    if isinstance(data, dict):
        shades = data.get("result", {}).get("reported", {}).get("shades", {})
        if isinstance(shades, dict):
            for sid, shade in shades.items():
                if isinstance(shade, dict):
                    result[str(sid).upper()] = {
                        "rssi": _to_int(shade.get("rs")),
                        "online": _to_bool(shade.get("ol")),
                    }
        return result
    # Not JSON even after repairs: read the fields straight from the text
    start = text.find('"shades"')
    if start < 0:
        return result
    for match in SHADE_RE.finditer(text, start):
        body = match.group(2)
        rs = re.search(FIELD_RE % "rs", body)
        ol = re.search(FIELD_RE % "ol", body)
        result[match.group(1).upper()] = {
            "rssi": _to_int(rs.group(1)) if rs else None,
            "online": _to_bool(ol.group(1)) if ol else None,
        }
    return result


class PulseProWebSocket:
    """Reads the hub's state once per call over a short-lived connection."""

    def __init__(self, host: str, port: int = WS_PORT) -> None:
        self.host = host
        self.port = port
        self._ssl = _ssl_context()

    async def async_fetch(self) -> dict[str, dict[str, Any]]:
        """Return the status of every blind. Raises WebSocketError."""
        try:
            async with asyncio.timeout(WS_TIMEOUT):
                return await self._fetch()
        except TimeoutError as err:
            raise WebSocketError("no reply from the hub") from err
        except (OSError, ssl.SSLError, ConnectionError, ValueError) as err:
            raise WebSocketError(str(err) or type(err).__name__) from err

    async def _fetch(self) -> dict[str, dict[str, Any]]:
        reader, writer = await asyncio.open_connection(
            self.host, self.port, ssl=self._ssl
        )
        try:
            key = base64.b64encode(os.urandom(16)).decode()
            writer.write(
                (
                    f"GET {WS_PATH} HTTP/1.1\r\n"
                    f"Host: {self.host}\r\n"
                    "Upgrade: websocket\r\n"
                    "Connection: Upgrade\r\n"
                    f"Sec-WebSocket-Key: {key}\r\n"
                    "Sec-WebSocket-Version: 13\r\n\r\n"
                ).encode()
            )
            await writer.drain()
            head = await reader.readuntil(b"\r\n\r\n")
            status = head.split(b"\r\n", 1)[0].decode(errors="replace")
            if " 101" not in status:
                raise WebSocketError(f"hub refused the WebSocket: {status}")

            query = {"method": "shadow", "src": "app", "id": int(time.time())}
            writer.write(_frame(0x1, json.dumps(query).encode()))
            await writer.drain()
            while True:
                text = await _read_message(reader, writer)
                if '"result"' in text:
                    return parse_shades(text)
        finally:
            with contextlib.suppress(Exception):
                writer.write(_frame(0x8, b""))
                writer.close()
                await asyncio.wait_for(writer.wait_closed(), 2)


def _frame(opcode: int, payload: bytes) -> bytes:
    """A masked client frame."""
    header = bytearray([0x80 | opcode])
    n = len(payload)
    if n < 126:
        header.append(0x80 | n)
    elif n < 65536:
        header += bytes([0x80 | 126]) + struct.pack("!H", n)
    else:
        header += bytes([0x80 | 127]) + struct.pack("!Q", n)
    mask = os.urandom(4)
    return bytes(header) + mask + bytes(b ^ mask[i % 4] for i, b in enumerate(payload))


async def _read_message(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> str:
    """Return the next text message (joins fragments, answers pings)."""
    parts: list[bytes] = []
    while True:
        b1, b2 = await reader.readexactly(2)
        n = b2 & 0x7F
        if n == 126:
            n = struct.unpack("!H", await reader.readexactly(2))[0]
        elif n == 127:
            n = struct.unpack("!Q", await reader.readexactly(8))[0]
        if n > 1_000_000:
            raise WebSocketError("message too large")
        mask = await reader.readexactly(4) if b2 & 0x80 else None
        data = await reader.readexactly(n)
        if mask:
            data = bytes(b ^ mask[i % 4] for i, b in enumerate(data))
        opcode = b1 & 0x0F
        if opcode == 0x8:
            raise WebSocketError("hub closed the WebSocket")
        if opcode == 0x9:
            writer.write(_frame(0xA, data))
            continue
        if opcode in (0x0, 0x1, 0x2):
            parts.append(data)
            if b1 & 0x80:
                return b"".join(parts).decode("utf-8", errors="replace")
