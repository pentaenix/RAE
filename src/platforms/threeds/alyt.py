"""Read named UI payloads from 3DS ALYT layouts and their embedded SARC.

ALYT layout tables precede a standard SARC archive. This reader deliberately
leaves the BFLYT/animation tables untouched and returns original file bytes.
Format reference: https://github.com/Tyulis/ALYTtool/blob/master/ALYT_ref.txt
"""
from __future__ import annotations

import struct
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class LayoutFile:
    name: str
    data: bytes


def read_alyt_files(data: bytes) -> list[LayoutFile]:
    """Extract the original named files, without resampling image data."""
    if len(data) < 0x28 or data[:4] != b"ALYT":
        raise ValueError("Missing ALYT header")
    start = data.find(b"SARC", 0x28)
    if start < 0:
        raise ValueError("ALYT has no embedded SARC")
    return read_sarc_files(data[start:])


def read_sarc_files(data: bytes) -> list[LayoutFile]:
    """Read a bounded little- or big-endian SARC file/name table."""
    data = bytes(data)
    if len(data) < 0x20 or data[:4] != b"SARC":
        raise ValueError("Missing SARC header")
    endian = {b"\xff\xfe": "<", b"\xfe\xff": ">"}.get(data[6:8])
    if endian is None:
        raise ValueError("Invalid SARC byte order")
    header = struct.unpack_from(endian + "H", data, 4)[0]
    size, base = struct.unpack_from(endian + "II", data, 8)
    if not 0x14 <= header <= base <= size <= len(data):
        raise ValueError("SARC file bounds exceed payload")
    if data[header:header + 4] != b"SFAT" or header + 12 > base:
        raise ValueError("Missing SARC allocation table")
    table_size, count = struct.unpack_from(endian + "HH", data, header + 4)
    nodes = header + table_size
    names = nodes + count * 16
    if table_size < 12 or names + 8 > base or data[names:names + 4] != b"SFNT":
        raise ValueError("Invalid SARC name table")
    name_size = struct.unpack_from(endian + "H", data, names + 4)[0]
    if name_size < 8 or names + name_size > base:
        raise ValueError("Invalid SARC name header")
    out = []
    for index in range(count):
        _, attributes, begin, end = struct.unpack_from(endian + "IIII", data, nodes + index * 16)
        if not 0 <= begin <= end <= size - base:
            raise ValueError("SARC entry exceeds data section")
        if attributes >> 24:
            offset = names + name_size + (attributes & 0xFFFFFF) * 4
            terminator = data.find(b"\x00", offset, base)
            if offset < names + name_size or terminator < 0:
                raise ValueError("SARC entry has an invalid name offset")
            name = data[offset:terminator].decode("utf-8")
        else:
            name = f"unnamed_{index:04d}.bin"
        out.append(LayoutFile(name, data[base + begin:base + end]))
    return out
