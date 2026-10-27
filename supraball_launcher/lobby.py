"""Client for the Supraball master server's TCP lobby (port 8992), enough to manage costumes.

Message types and fields were learned from the official launcher's traffic (docs/master-protocol.md).
"""

from __future__ import annotations

import socket

from . import wire
from .master import MASTER_HOST
from .steamhelper import SteamSession

LOBBY_PORT = 8992
LAUNCHER_VERSION = "1.0.0"  # what the official launcher reports

# Client -> server
AUTHENTICATE = 0
PING = 20  # the server answers with type 18, which _read skips
CHANGE_ASSET_CONFIG = 28
GET_ASSET_CONFIGS = 29
# Server -> client
RESPONSE = 7
ASSET_CONFIGS = 31
GREETING = 33


class LobbyError(RuntimeError):
    pass


def encode_authenticate(session: SteamSession) -> bytes:
    return wire.encode_fields([(1, session.ticket), (2, session.name), (4, session.country),
                               (6, LAUNCHER_VERSION), (7, 0)])


def decode_response(body: bytes) -> tuple[int, str]:
    fields = {f: v for f, _, v in wire.decode_fields(body)}
    message = fields.get(2, b"")
    return int(fields.get(1, 0)), message.decode(errors="replace") if isinstance(message, bytes) else str(message)


def decode_asset_configs(body: bytes) -> list[int]:
    """Definitions of the equipped items."""
    equipped = []
    for field, wire_type, value in wire.decode_fields(body):
        if field == 1 and wire_type == 2:
            config = {f: v for f, _, v in wire.decode_fields(value)}
            if config.get(3, 1):
                equipped.append(int(config[1]))
    return equipped


class LobbyClient:
    def __init__(self, host: str = MASTER_HOST, port: int = LOBBY_PORT, timeout: float = 15):
        self.host, self.port, self.timeout = host, port, timeout
        self.sock: socket.socket | None = None
        self._buf = b""
        self._next_id = 1

    def __enter__(self) -> "LobbyClient":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def close(self) -> None:
        if self.sock:
            self.sock.close()
            self.sock = None

    def _send(self, packet_type: int, body: bytes = b"") -> int:
        packet_id = self._next_id
        self._next_id += 1
        self.sock.sendall(wire.encode_frame(packet_id, packet_type, body))
        return packet_id

    def _read(self, packet_type: int, packet_id: int | None = None) -> wire.Frame:
        """Wait for a frame of this type (and id), skipping the unsolicited updates the server pushes."""
        while True:
            frames, _ = wire.split_frames(self._buf)
            consumed = 0
            for frame in frames:
                consumed += wire.HEADER.size + len(frame.body)
                if frame.packet_type == packet_type and (packet_id is None or frame.packet_id == packet_id):
                    self._buf = self._buf[consumed:]
                    return frame
            self._buf = self._buf[consumed:]
            try:
                chunk = self.sock.recv(65536)
            except socket.timeout as e:
                raise LobbyError("The Supraball server stopped responding.") from e
            if not chunk:
                raise LobbyError("The Supraball server closed the connection.")
            self._buf += chunk

    def _expect_ok(self, packet_id: int, action: str) -> None:
        code, message = decode_response(self._read(RESPONSE, packet_id).body)
        if code != 0:
            raise LobbyError(f"{action} failed: {message or f'error {code}'}")

    def connect(self, session: SteamSession) -> None:
        try:
            self.sock = socket.create_connection((self.host, self.port), timeout=self.timeout)
        except OSError as e:
            raise LobbyError(f"Can't reach the Supraball server at {self.host}:{self.port}.") from e
        self.sock.settimeout(self.timeout)
        self._read(GREETING)
        self._expect_ok(self._send(AUTHENTICATE, encode_authenticate(session)), "Signing in")

    def equipped(self) -> list[int]:
        packet_id = self._send(GET_ASSET_CONFIGS)
        return decode_asset_configs(self._read(ASSET_CONFIGS, packet_id).body)

    def ping(self) -> None:
        """Keep the connection alive, like the official launcher does every 10 s."""
        self._send(PING)

    def set_equipped(self, definition: int, equipped: bool = True) -> None:
        """Equip an item (the server swaps out whatever was in the same slot) or take it off."""
        body = wire.encode_fields([(1, definition), (3, int(equipped))])
        self._expect_ok(self._send(CHANGE_ASSET_CONFIG, body), "Changing your costume")
