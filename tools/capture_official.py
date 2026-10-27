"""Record the official launcher's traffic with the Supraball master server.

Usage:  uv run python tools/capture_official.py

Makes a temporary copy of launcher/supraball-launcher.exe whose master hostname points
at 127.0.0.1, runs a forwarding proxy on the master's ports, and starts that copy through
Proton. Use it normally (sign in, open your equipment, equip something), then close it.
Every byte in both directions is saved to captures/<timestamp>.jsonl, and the copy is deleted.
"""

from __future__ import annotations

import json
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from supraball_launcher import game, paths  # noqa: E402
from supraball_launcher.wire import describe_stream  # noqa: E402

MASTER = "master.supraball.net"
PORTS = (8991, 8992, 2000)
PATCHED_NAME = "supraball-launcher-capture.exe"


def patch_exe(src: Path, dst: Path) -> None:
    data = src.read_bytes()
    needle = MASTER.encode() + b"\0"
    if data.count(needle) != 1:
        raise SystemExit(f"Expected exactly one '{MASTER}' in {src}, found {data.count(needle)}")
    replacement = b"127.0.0.1".ljust(len(needle), b"\0")
    dst.write_bytes(data.replace(needle, replacement))


class Recorder:
    def __init__(self, out: Path):
        self.out = out.open("w")
        self.lock = threading.Lock()
        self.t0 = time.monotonic()
        self.streams: dict[tuple[int, int, str], bytearray] = {}

    def record(self, conn: int, port: int, direction: str, data: bytes) -> None:
        with self.lock:
            self.out.write(json.dumps({"t": round(time.monotonic() - self.t0, 3), "conn": conn, "port": port,
                                       "dir": direction, "hex": data.hex()}) + "\n")
            self.out.flush()
            self.streams.setdefault((conn, port, direction), bytearray()).extend(data)
        arrow = "launcher → master" if direction == "c2s" else "master → launcher"
        print(f"[{port} #{conn}] {arrow}: {len(data)} bytes", flush=True)


def pump(src: socket.socket, dst: socket.socket, rec: Recorder, conn: int, port: int, direction: str) -> None:
    try:
        while data := src.recv(65536):
            rec.record(conn, port, direction, data)
            dst.sendall(data)
    except OSError:
        pass
    finally:
        for s in (src, dst):
            try:
                s.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass


def serve(port: int, rec: Recorder, counter: list[int]) -> socket.socket:
    listener = socket.create_server(("127.0.0.1", port), reuse_port=False)

    def accept_loop() -> None:
        while True:
            try:
                client, _ = listener.accept()
            except OSError:
                return
            counter[0] += 1
            conn = counter[0]
            upstream = socket.create_connection((MASTER, port), timeout=10)
            upstream.settimeout(None)
            print(f"[{port} #{conn}] connected", flush=True)
            threading.Thread(target=pump, args=(client, upstream, rec, conn, port, "c2s"), daemon=True).start()
            threading.Thread(target=pump, args=(upstream, client, rec, conn, port, "s2c"), daemon=True).start()

    threading.Thread(target=accept_loop, daemon=True).start()
    return listener


def main() -> None:
    p = paths.detect()
    original = p.game_dir / "launcher/supraball-launcher.exe"
    patched = original.with_name(PATCHED_NAME)
    captures = ROOT / "captures"
    captures.mkdir(exist_ok=True)
    out = captures / f"{time.strftime('%Y%m%d-%H%M%S')}.jsonl"

    rec = Recorder(out)
    counter = [0]
    listeners = [serve(port, rec, counter) for port in PORTS]
    patch_exe(original, patched)
    print(f"Recording to {out}\nStarting the official launcher. Sign in, open your equipment, equip a couple of items, then close it.\n")
    try:
        argv, env = game.proton_command(p, [], exe=patched)
        subprocess.run(argv, env=env, cwd=p.game_dir)  # it finds UDK.exe relative to the game root
    finally:
        patched.unlink(missing_ok=True)
        for listener in listeners:
            listener.close()
        rec.out.close()

    print("\nSummary:")
    for (conn, port, direction), data in sorted(rec.streams.items()):
        print(f"\n== port {port} conn #{conn} {direction} ({len(data)} bytes)")
        print(describe_stream(bytes(data)) if port == 8992 else data[:300])
    print(f"\nSaved {out}")


if __name__ == "__main__":
    main()
