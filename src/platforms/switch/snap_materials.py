"""Resolve Snap model shape assignments and material instance texture slots."""
from __future__ import annotations

import struct

from .flatbuf import read_string, read_table_vector, root_offset, table_fields, vector_len, vector_offset


def read_model_bindings(data: bytes) -> tuple[str, dict[tuple[str, int], str]]:
    if len(data) < 88 or data[:4] != b"HBSS" or data[16:24] != b"LDOM\x01\x00\x07\x00":
        raise ValueError("Expected a Snap SSBH Model 1.7 payload")

    def ssbh_name(field: int) -> str:
        offset = field + struct.unpack_from("<Q", data, field)[0]
        if offset >= len(data):
            raise ValueError("Snap model string exceeds its payload")
        return data[offset:data.index(b"\0", offset)].decode("ascii")

    offset, count = struct.unpack_from("<QQ", data, 72)
    start = 72 + offset
    if start + count * 24 > len(data):
        raise ValueError("Snap material assignments exceed the model payload")
    assignments = {}
    for entry in range(start, start + count * 24, 24):
        subindex = struct.unpack_from("<Q", data, entry + 8)[0]
        assignments[ssbh_name(entry), subindex] = ssbh_name(entry + 16)
    return ssbh_name(64), assignments


def read_texture_slots(data: bytes) -> dict[str, str]:
    root = table_fields(data, root_offset(data))
    field = root.get(4)
    if field is None or vector_len(data, vector_offset(data, field)) > 64:
        raise ValueError("Unexpected Snap material texture list")
    slots = {}
    for entry in read_table_vector(data, field):
        label, texture = entry.get(7), entry.get(1)
        if label is not None and texture is not None:
            slots[read_string(data, label)] = read_string(data, texture)
    return slots
