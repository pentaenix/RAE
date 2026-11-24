"""Range reader for Snap DRPF packs (format reference: kwsch/NewSnap)."""
from __future__ import annotations

import struct
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from zlib import crc32

from .oodle import decompress

DRPF_MAGIC = 0x7F0E5359
_HEADER_MAGIC = 0xC65753E8
_MEMBER_MAGIC = 0xE0A331B4
_OODLE_MAGIC = b"\xba\x98\x2d\xe4"
_HEADER_SIZE = 0x94
_MEMBER_HEADER_SIZE = 24
_MASK = 0xFFFFFFFF


def _signed(value: int) -> int:
    return value if value < 0x80000000 else value - 0x100000000


def _random31(seed: int, table: bytes) -> Iterator[int]:
    seed = int.from_bytes(bytes(table[index & 0x7F] for index in seed.to_bytes(4, "little")), "little")
    state = []
    for _ in range(4):
        seed = (0x41C64E6D * seed + 12345) & _MASK
        state.append(seed)
    w, z, y, x = state
    while True:
        mixed = (x ^ (x << 11)) & _MASK
        x, y, z, w = y, z, w, (w ^ (_signed(w) >> 19) ^ mixed ^ (_signed(mixed) >> 8)) & _MASK
        yield w & 0x7FFFFFFF


def _crypt(data: bytes, start: int, seed: int, table: bytes) -> bytearray:
    output = bytearray(data)
    random31 = _random31(seed, table)
    for offset in range(start, len(data), 4):
        (value,) = struct.unpack_from("<I", data, offset)
        key = next(random31) | ((next(random31) & 0x40000000) << 1)
        struct.pack_into("<I", output, offset, value ^ key)
    return output


@dataclass(frozen=True, slots=True)
class DrpMember:
    name: str
    type_hash: int
    offset: int
    data_offset: int
    stored_size: int
    decoded_size: int


class DrpPack:
    def __init__(self, read: Callable[[int, int], bytes], size: int):
        self._read = read
        self._size = size
        if size < _HEADER_SIZE or size % 4:
            raise ValueError("Invalid Snap pack length")
        raw = self._range(0, _HEADER_SIZE)
        magic, seed, crypto_magic = struct.unpack_from("<III", raw)
        if magic != DRPF_MAGIC:
            raise ValueError("Invalid Snap pack signature")
        self._table = raw[20:]
        self._encrypted = crypto_magic != _HEADER_MAGIC
        header = _crypt(raw[:20], 8, seed, self._table) + self._table if self._encrypted else raw
        marker, header_size, self._count = struct.unpack_from("<III", header, 8)
        if (marker, header_size) != (_HEADER_MAGIC, 0x90) or crc32(header[16:]) != seed:
            raise ValueError("Invalid Snap pack header checksum")
        if self._count > (size - _HEADER_SIZE) // _MEMBER_HEADER_SIZE:
            raise ValueError("Invalid Snap pack member count")

    def _range(self, offset: int, length: int) -> bytes:
        if offset < 0 or length < 0 or offset + length > self._size:
            raise ValueError("Snap pack range exceeds archive bounds")
        data = self._read(offset, length)
        if len(data) != length:
            raise ValueError("Truncated Snap pack")
        return data

    def _member_range(self, offset: int, length: int) -> bytes | bytearray:
        data = self._range(offset, length)
        if not self._encrypted:
            return data
        (seed,) = struct.unpack_from("<I", data)
        return _crypt(data, 4, seed, self._table)

    def members(self) -> Iterator[DrpMember]:
        offset = _HEADER_SIZE
        for _ in range(self._count):
            header = self._member_range(offset, _MEMBER_HEADER_SIZE)
            _, magic, chunk_size, type_hash, stored_size, decoded_size = struct.unpack("<6I", header)
            if (magic != _MEMBER_MAGIC or chunk_size % 4
                    or not _MEMBER_HEADER_SIZE + 4 <= chunk_size <= self._size - offset):
                raise ValueError("Invalid Snap pack member header")
            prefix = self._member_range(offset, min(chunk_size, _MEMBER_HEADER_SIZE + 256))
            end = prefix.find(b"\0", _MEMBER_HEADER_SIZE)
            if end <= _MEMBER_HEADER_SIZE:
                raise ValueError("Invalid Snap pack member name")
            name = prefix[_MEMBER_HEADER_SIZE:end].decode("ascii")
            data_offset = (end + 4) & ~3
            if data_offset + stored_size > chunk_size:
                raise ValueError(f"Invalid Snap pack member length for {name}")
            yield DrpMember(name, type_hash, offset, data_offset, stored_size, decoded_size)
            offset += chunk_size

    def payload(self, member: DrpMember) -> bytes:
        end = member.data_offset + member.stored_size
        if max(end, member.decoded_size) > 64 * 1024 * 1024:
            raise ValueError(f"Snap preview member is too large: {member.name}")
        decoded = self._member_range(member.offset, (end + 3) & ~3)
        payload = bytes(decoded[member.data_offset:end])
        if payload.startswith(_OODLE_MAGIC):
            payload = decompress(payload[4:], member.decoded_size)
        if len(payload) != member.decoded_size:
            raise ValueError(f"Snap pack member length mismatch for {member.name}")
        return payload
