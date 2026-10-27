"""Minimal protobuf wire format plus the master server's TCP framing (port 8992).

Framing, inferred from the server's greeting `00 00 21 03 00 00 00 10 dd 03`:
    u16 little-endian packet id, u8 packet type, u32 little-endian body length, protobuf body.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass

HEADER = struct.Struct("<HBI")


@dataclass
class Frame:
    packet_id: int
    packet_type: int
    body: bytes


def encode_frame(packet_id: int, packet_type: int, body: bytes) -> bytes:
    return HEADER.pack(packet_id, packet_type, len(body)) + body


def split_frames(data: bytes) -> tuple[list[Frame], bytes]:
    """Parse as many whole frames as data holds; returns (frames, leftover bytes)."""
    frames = []
    pos = 0
    while len(data) - pos >= HEADER.size:
        packet_id, packet_type, length = HEADER.unpack_from(data, pos)
        end = pos + HEADER.size + length
        if end > len(data):
            break
        frames.append(Frame(packet_id, packet_type, data[pos + HEADER.size:end]))
        pos = end
    return frames, data[pos:]


# --- protobuf wire format -------------------------------------------------

def encode_varint(value: int) -> bytes:
    if value < 0:
        value += 1 << 64
    out = bytearray()
    while True:
        byte = value & 0x7F
        value >>= 7
        if value:
            out.append(byte | 0x80)
        else:
            out.append(byte)
            return bytes(out)


def decode_varint(buf: bytes, pos: int) -> tuple[int, int]:
    result = shift = 0
    while True:
        if pos >= len(buf) or shift > 63:
            raise ValueError("truncated varint")
        b = buf[pos]
        pos += 1
        result |= (b & 0x7F) << shift
        if not b & 0x80:
            return result, pos
        shift += 7


def decode_fields(buf: bytes) -> list[tuple[int, int, int | bytes]]:
    """Decode a message into (field_number, wire_type, value) without a schema. Raises ValueError if invalid."""
    fields = []
    pos = 0
    while pos < len(buf):
        key, pos = decode_varint(buf, pos)
        field, wire = key >> 3, key & 7
        if field == 0:
            raise ValueError("field number 0")
        if wire == 0:
            value, pos = decode_varint(buf, pos)
        elif wire == 1:
            value, pos = int.from_bytes(buf[pos:pos + 8], "little"), pos + 8
        elif wire == 2:
            length, pos = decode_varint(buf, pos)
            if pos + length > len(buf):
                raise ValueError("truncated bytes")
            value, pos = buf[pos:pos + length], pos + length
        elif wire == 5:
            value, pos = int.from_bytes(buf[pos:pos + 4], "little"), pos + 4
        else:
            raise ValueError(f"wire type {wire}")
        if pos > len(buf):
            raise ValueError("truncated")
        fields.append((field, wire, value))
    return fields


def encode_fields(fields: list[tuple[int, int | str | bytes | list]]) -> bytes:
    """Encode (field_number, value) pairs: ints as varints, str/bytes as length-delimited,
    lists of pairs as nested messages."""
    out = bytearray()
    for field, value in fields:
        if isinstance(value, bool) or isinstance(value, int):
            out += encode_varint(field << 3) + encode_varint(int(value))
        else:
            if isinstance(value, str):
                value = value.encode()
            elif isinstance(value, list):
                value = encode_fields(value)
            out += encode_varint(field << 3 | 2) + encode_varint(len(value)) + value
    return bytes(out)


def describe(buf: bytes, indent: int = 0) -> str:
    """Human-readable schema-less dump, guessing nested messages and strings."""
    pad = "  " * indent
    try:
        fields = decode_fields(buf)
    except ValueError:
        return f"{pad}<raw {buf.hex()}>"
    lines = []
    for field, wire, value in fields:
        if wire == 2:
            text = None
            try:
                s = value.decode("utf-8")
                if s.isprintable():
                    text = s
            except UnicodeDecodeError:
                pass
            nested = None
            if value and text is None:
                try:
                    decode_fields(value)
                    nested = describe(value, indent + 1)
                except ValueError:
                    pass
            if text is not None:
                lines.append(f"{pad}{field}: {text!r}")
            elif nested is not None:
                lines.append(f"{pad}{field}: {{\n{nested}\n{pad}}}")
            else:
                lines.append(f"{pad}{field}: <bytes {len(value)}: {value[:48].hex()}{'…' if len(value) > 48 else ''}>")
        else:
            lines.append(f"{pad}{field}: {value}")
    return "\n".join(lines) if lines else f"{pad}<empty>"


def describe_stream(data: bytes) -> str:
    frames, rest = split_frames(data)
    parts = [f"-- id={f.packet_id} type={f.packet_type} len={len(f.body)}\n{describe(f.body, 1)}" for f in frames]
    if rest:
        parts.append(f"-- leftover {len(rest)} bytes: {rest[:64].hex()}")
    return "\n".join(parts)
