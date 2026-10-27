"""Supraball master server list and Source-style (A2S) server pings."""

from __future__ import annotations

import json
import socket
import struct
import time
import urllib.request
from dataclasses import dataclass

MASTER_HOST = "master.supraball.net"
MASTER_PORT = 8991  # DBMasterServer default property in DBGame.u

A2S_INFO = b"\xff\xff\xff\xffTSource Engine Query\x00"
A2S_PLAYER = b"\xff\xff\xff\xffU"
NO_CHALLENGE = b"\xff\xff\xff\xff"


class MasterError(RuntimeError):
    pass


@dataclass
class PlayerInfo:
    name: str
    score: int
    seconds: float


@dataclass
class ServerEntry:
    name: str
    ip: str
    port: int
    query_port: int
    map: str = ""
    type: str = ""
    version: str = ""
    ranked: bool = False
    passworded: bool = False
    players: int = 0
    max_players: int = 0
    spectators: int = 0
    max_spectators: int = 0
    timelimit: int = 0
    current_time: int = 0
    ping: int | None = None

    @property
    def address(self) -> str:
        return f"{self.ip}:{self.port}"

    @classmethod
    def from_json(cls, d: dict) -> "ServerEntry":
        return cls(
            name=str(d.get("name", "")),
            ip=str(d.get("ip", "")),
            port=int(d.get("port", 7777)),
            query_port=int(d.get("query_port", 27015)),
            map=str(d.get("map", "")),
            type=str(d.get("type", "")),
            version=str(d.get("_version", "")),
            ranked=bool(d.get("ranked", False)),
            passworded=bool(d.get("passworded", False)),
            players=int(d.get("players", 0)),
            max_players=int(d.get("max_players", 0)),
            spectators=int(d.get("spectators", 0)),
            max_spectators=int(d.get("max_spectators", 0)),
            timelimit=int(d.get("timelimit", 0)),
            current_time=int(d.get("current_time", 0)),
        )


def parse_server_list(raw: bytes) -> list[ServerEntry]:
    # Some fields (e.g. "region") contain bytes that aren't valid UTF-8.
    data = json.loads(raw.decode("utf-8", errors="replace"))
    return [ServerEntry.from_json(s) for s in data.get("servers", []) if s.get("ip")]


def fetch_servers(host: str = MASTER_HOST, port: int = MASTER_PORT, timeout: float = 8.0) -> list[ServerEntry]:
    req = urllib.request.Request(f"http://{host}:{port}/list", headers={"Origin": "supraball"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read()
    except OSError as e:
        raise MasterError(f"Master server {host}:{port} unreachable: {e}") from e
    try:
        return parse_server_list(raw)
    except (ValueError, AttributeError) as e:
        raise MasterError(f"Unexpected reply from master server: {e}") from e


def a2s_ping(ip: str, query_port: int, timeout: float = 1.5) -> int | None:
    """Round-trip time in ms of an A2S_INFO query, or None if the server doesn't answer."""
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        s.settimeout(timeout)
        try:
            start = time.monotonic()
            s.sendto(A2S_INFO, (ip, query_port))
            data, _ = s.recvfrom(1400)
            if data[4:5] == b"A":  # challenge: resend with it, time the real answer
                start = time.monotonic()
                s.sendto(A2S_INFO + data[5:9], (ip, query_port))
                data, _ = s.recvfrom(1400)
            if data[4:5] != b"I":
                return None
            return round((time.monotonic() - start) * 1000)
        except OSError:
            return None


def parse_players(data: bytes) -> list[PlayerInfo]:
    """Players from a single-packet A2S_PLAYER reply ('D')."""
    count, pos, players = data[5], 6, []
    for _ in range(count):
        end = data.index(b"\x00", pos + 1)  # skip the index byte
        name = data[pos + 1:end].decode("utf-8", errors="replace")
        score, seconds = struct.unpack_from("<lf", data, end + 1)
        players.append(PlayerInfo(name, score, seconds))
        pos = end + 9
    return players


def a2s_players(ip: str, query_port: int, timeout: float = 1.5) -> list[PlayerInfo] | None:
    """Who's on the server, or None if it doesn't answer A2S_PLAYER."""
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        s.settimeout(timeout)
        try:
            s.sendto(A2S_PLAYER + NO_CHALLENGE, (ip, query_port))
            data, _ = s.recvfrom(1400)
            if data[4:5] == b"A":
                s.sendto(A2S_PLAYER + data[5:9], (ip, query_port))
                data, _ = s.recvfrom(1400)
            if data[:5] != b"\xff\xff\xff\xffD":
                return None
            return parse_players(data)
        except (OSError, ValueError, IndexError, struct.error):
            return None
