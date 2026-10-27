"""Read Qt resources (rcc data compiled into an exe).

Used to get the costume artwork (images/Skins/<item>.png, images/Hats/<item>.png and their masks)
out of the official Supraball launcher; the item icons it links online are no longer reachable.

CLI: python -m supraball_launcher.qt_resources <exe> <top-level dir> <output dir> [path prefix ...]

rcc layout: a names blob of (u16 length, u32 hash, UTF-16BE name) entries; a tree of fixed-size
nodes (u32 name offset, u16 flags, then u32 child count + u32 first child for directories, or
u16 country, u16 language, u32 data offset for files; format v2+ appends a u64 timestamp); and a
data blob of (u32 size, bytes) entries, zlib-compressed (after a u32 length) when flags & 1.
"""

from __future__ import annotations

import struct
import sys
import zlib
from pathlib import Path

DIR, COMPRESSED = 0x02, 0x01
IMAGE_MAGIC = (b"\x89PNG", b"\xff\xd8\xff\xe0", b"\xff\xd8\xff\xe1", b"\xff\xd8\xff\xdb")


class ResourceError(RuntimeError):
    pass


def _name_at(d: bytes, names: int, offset: int) -> str:
    length = struct.unpack_from(">H", d, names + offset)[0]
    return d[names + offset + 6:names + offset + 6 + 2 * length].decode("utf-16-be")


def _names_start(d: bytes, entry: int) -> int:
    """Walk backwards from a known names entry to the start of its names blob."""
    start = entry
    while True:
        for length in range(1, 256):
            p = start - 6 - 2 * length
            if p < 0:
                return start
            if struct.unpack_from(">H", d, p)[0] != length:
                continue
            try:
                if d[p + 6:start].decode("utf-16-be").isprintable():
                    start = p
                    break
            except UnicodeDecodeError:
                continue
        else:
            return start


def list_files(d: bytes, top: str) -> list[tuple[str, bytes]]:
    """All files under the top-level resource directory `top`, as (path, raw entry) pairs."""
    idx = d.find(top.encode("utf-16-be"))
    while idx != -1 and struct.unpack_from(">H", d, idx - 6)[0] != len(top):
        idx = d.find(top.encode("utf-16-be"), idx + 1)
    if idx == -1:
        raise ResourceError(f"No resource directory named {top!r}.")
    names = _names_start(d, idx - 6)
    if idx - 6 != names:
        raise ResourceError("Only a directory at the start of its resource bundle is supported.")

    def plausible(tree: int, size: int) -> bool:
        try:
            _, _, count, first = struct.unpack_from(">IHII", d, tree + size)
            if not 0 < count < 100000:
                return False
            for i in range(first, first + min(count, 20)):
                if not _name_at(d, names, struct.unpack_from(">I", d, tree + i * size)[0]).isprintable():
                    return False
            return True
        except (struct.error, UnicodeDecodeError):
            return False

    # Each compiled .qrc has its own tree. Its root is (name 0, DIR, 1 child, first child 1);
    # take the one nearest this names blob whose children decode against it.
    root = struct.pack(">IHII", 0, DIR, 1, 1)
    candidates = []
    pos = d.find(root)
    while pos != -1:
        candidates.append(pos)
        pos = d.find(root, pos + 1)
    candidates.sort(key=lambda c: abs(c - names))
    tree = size = None
    for c in candidates:
        size = next((sz for sz in (14, 22) if plausible(c, sz)), None)
        if size:
            tree = c
            break
    if tree is None:
        raise ResourceError("Couldn't find the resource tree.")

    files: list[tuple[str, int, int]] = []

    def walk(index: int, path: str) -> None:
        off, flags = struct.unpack_from(">IH", d, tree + index * size)
        name = _name_at(d, names, off)
        if flags & DIR:
            _, _, count, first = struct.unpack_from(">IHII", d, tree + index * size)
            for child in range(first, first + count):
                walk(child, f"{path}/{name}")
        else:
            files.append((f"{path}/{name}"[1:], flags, struct.unpack_from(">I", d, tree + index * size + 10)[0]))

    walk(1, "")

    # The data blob start isn't recorded anywhere we can see; find the offset at which every
    # uncompressed image entry lines up with an image header.
    plain = [(o) for _, fl, o in files if not fl & COMPRESSED]
    if not plain:
        raise ResourceError("No uncompressed files to anchor the data blob.")
    anchor = plain[0]

    def aligned(data: int, offsets) -> bool:
        return all(d[data + o + 4:data + o + 8] in IMAGE_MAGIC for o in offsets)

    data = None
    for magic in IMAGE_MAGIC:
        pos = d.find(magic)
        while pos != -1:
            candidate = pos - 4 - anchor
            if candidate >= 0 and aligned(candidate, plain[:8]) and aligned(candidate, plain):
                data = candidate
                break
            pos = d.find(magic, pos + 1)
        if data is not None:
            break
    if data is None:
        raise ResourceError("Couldn't find the resource data.")

    out = []
    for path, flags, off in files:
        length = struct.unpack_from(">I", d, data + off)[0]
        payload = d[data + off + 4:data + off + 4 + length]
        out.append((path, zlib.decompress(payload[4:]) if flags & COMPRESSED else payload))
    return out


def extract(exe: Path, top: str, out: Path, prefixes: tuple[str, ...] = ()) -> int:
    """Write files under `top` (optionally only paths starting with one of `prefixes`) to `out`."""
    count = 0
    for path, payload in list_files(exe.read_bytes(), top):
        if prefixes and not path.startswith(prefixes):
            continue
        target = out / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(payload)
        count += 1
    return count


if __name__ == "__main__":
    exe, top, dest, *prefixes = sys.argv[1:]
    print(f"extracted {extract(Path(exe), top, Path(dest), tuple(prefixes))} files to {dest}")
