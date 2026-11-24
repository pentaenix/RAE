"""Bounded GFPAK reader for Sword/Shield model archives.

GFPAK layout documented by pkNX and lincoln-lm's gfpak.py. Names are FNV-1a
hashes; retain both the per-folder and absolute hashes without guessing identity.
"""
from dataclasses import dataclass
import struct


@dataclass(frozen=True)
class GfpakFile:
    index: int
    name_hash: int
    absolute_hash: int
    data: bytes


def read_gfpak(data: bytes) -> list[GfpakFile]:
    import lz4.block
    if len(data) < 40 or data[:8] != b"GFLXPACK":
        raise ValueError("Not a GFPAK archive")
    version, relocated, count, folders = struct.unpack_from("<IIII", data, 8)
    table, paths = struct.unpack_from("<QQ", data, 24)
    if version != 0x1000 or relocated or count > 100000 or folders > count:
        raise ValueError("Unsupported GFPAK header")
    if table + 24 * count > len(data) or paths + 8 * count > len(data) or 40 + folders * 8 > len(data):
        raise ValueError("GFPAK index exceeds file")
    hashes = struct.unpack_from(f"<{count}Q", data, paths)
    names = {}
    for i in range(folders):
        offset = struct.unpack_from("<Q", data, 40 + i * 8)[0]
        if offset + 16 > len(data):
            raise ValueError("Truncated GFPAK folder")
        _, size, _ = struct.unpack_from("<QII", data, offset)
        if size > count or offset + 16 + size * 16 > len(data):
            raise ValueError("Invalid GFPAK folder size")
        for j in range(size):
            name, index, _ = struct.unpack_from("<QII", data, offset + 16 + j * 16)
            if index >= count or index in names:
                raise ValueError("Duplicate/out-of-range GFPAK file index")
            names[index] = name
    if len(names) != count:
        raise ValueError("GFPAK folder index omits files")
    files = []
    for i in range(count):
        _, codec, unpacked, packed, _, offset = struct.unpack_from("<HHIIIQ", data, table + i * 24)
        if unpacked > 512 * 1024 * 1024 or offset + packed > len(data):
            raise ValueError("GFPAK payload exceeds bounds")
        payload = data[offset:offset + packed]
        if codec == 2:
            payload = lz4.block.decompress(payload, uncompressed_size=unpacked)
        elif codec != 0:
            raise ValueError(f"Unsupported GFPAK codec {codec}")
        if len(payload) != unpacked:
            raise ValueError("GFPAK payload length mismatch")
        files.append(GfpakFile(i, names[i], hashes[i], payload))
    return files
