"""Decode base mip levels of ordinary 2D Switch BNTX textures.

The Tegra X1 block-linear address is defined in its texture memory layout.
Array, volume and signed/float formats are deliberately rejected, not guessed.
"""
from __future__ import annotations

import struct
from dataclasses import dataclass


class UnsupportedTextureError(ValueError):
    """A valid texture type that has no portable 2D base-color decoder."""


@dataclass(frozen=True)
class Texture:
    name: str
    width: int
    height: int
    format: int
    rgba: bytes


def _slice(data: bytes, offset: int, size: int) -> bytes:
    if offset < 0 or size < 0 or offset + size > len(data):
        raise ValueError("BNTX data range exceeds file bounds")
    return data[offset:offset + size]


def _number(data: bytes, offset: int, fmt: str) -> int:
    return struct.unpack(fmt, _slice(data, offset, struct.calcsize(fmt)))[0]


def deswizzle(data: bytes, width: int, height: int, bpp: int,
              block_height_log2: int, *, linear: bool = False) -> bytes:
    """Untile a surface measured in compression blocks (or raw pixels)."""
    if not (0 < width <= 16384 and 0 < height <= 16384 and 0 <= block_height_log2 <= 5):
        raise ValueError("Invalid BNTX surface dimensions or block height")
    block_height = 1 << block_height_log2
    gobs = (width * bpp + 63) // 64
    pitch = (width * bpp + 31) // 32 * 32
    output = bytearray(width * height * bpp)
    for y in range(height):
        for x in range(width):
            xb = x * bpp
            if linear:
                address = y * pitch + xb
            else:
                address = ((y // (8 * block_height)) * 512 * block_height * gobs
                           + (xb // 64) * 512 * block_height
                           + (y % (8 * block_height) // 8) * 512
                           + (xb % 64 // 32) * 256 + (y % 8 // 2) * 64
                           + (xb % 32 // 16) * 32 + (y % 2) * 16 + xb % 16)
            start = (y * width + x) * bpp
            output[start:start + bpp] = _slice(data, address, bpp)
    return bytes(output)


def _decode(payload: bytes, width: int, height: int, fmt: int) -> bytes:
    kind = fmt >> 8
    if kind == 0x0B:
        return payload
    if kind in (0x02, 0x09):
        components = 1 if kind == 0x02 else 2
        result = bytearray()
        for i in range(0, len(payload), components):
            result.extend((payload[i], payload[i + 1] if components == 2 else 0, 0, 255))
        return bytes(result)
    if kind == 0x1B:
        return _decode_bc2(payload, width, height)
    import texture2ddecoder

    decoder = {0x1A: "decode_bc1", 0x1B: "decode_bc2", 0x1C: "decode_bc3",
               0x1D: "decode_bc4", 0x1E: "decode_bc5", 0x20: "decode_bc7"}.get(kind)
    if decoder is None:
        raise ValueError(f"Unsupported BNTX texture format 0x{fmt:04x}")
    bgra = getattr(texture2ddecoder, decoder)(payload, width, height)
    rgba = bytearray(bgra)
    rgba[0::4], rgba[2::4] = bgra[2::4], bgra[0::4]
    return bytes(rgba)


def _decode_bc2(payload: bytes, width: int, height: int) -> bytes:
    """BC2 has explicit four-bit alpha and always uses four color entries."""
    result = bytearray(width * height * 4)
    for by in range((height + 3) // 4):
        for bx in range((width + 3) // 4):
            offset = (by * ((width + 3) // 4) + bx) * 16
            alpha, c0, c1, codes = struct.unpack_from("<QHHI", payload, offset)
            colors = [tuple(((c >> shift) & mask) * 255 // mask
                            for shift, mask in ((11, 31), (5, 63), (0, 31)))
                      for c in (c0, c1)]
            colors.extend(tuple((2 * a + b) // 3 for a, b in zip(colors[i], colors[1-i]))
                          for i in range(2))
            for pixel in range(16):
                x, y = bx * 4 + pixel % 4, by * 4 + pixel // 4
                if x < width and y < height:
                    start = (y * width + x) * 4
                    result[start:start+4] = bytes((*colors[(codes >> (2*pixel)) & 3],
                                                  ((alpha >> (4*pixel)) & 15) * 17))
    return bytes(result)


def decode_bntx(data: bytes) -> list[Texture]:
    if data[:8] != b"BNTX\0\0\0\0" or data[12:14] != b"\xff\xfe":
        raise ValueError("Expected a little-endian BNTX texture")
    if _slice(data, 32, 4) != b"NX  ":
        raise ValueError("Expected a Switch NX BNTX texture")
    count = _number(data, 36, "<I")
    pointers = _number(data, 40, "<Q")
    if count > 1024:
        raise ValueError("Too many BNTX textures")
    result = []
    for i in range(count):
        info = _number(data, pointers + 8 * i, "<Q")
        if _slice(data, info, 4) != b"BRTI":
            raise ValueError("Missing BNTX BRTI texture header")
        dimension = _number(data, info + 0x11, "<B")
        tile_mode = _number(data, info + 0x12, "<H")
        fmt = _number(data, info + 0x1C, "<I")
        width = _number(data, info + 0x24, "<I")
        height = _number(data, info + 0x28, "<I")
        if not (0 < width <= 16384 and 0 < height <= 16384):
            raise ValueError("Invalid BNTX pixel dimensions")
        depth = _number(data, info + 0x2C, "<I")
        layers = _number(data, info + 0x30, "<I")
        block_height = _number(data, info + 0x34, "<I") & 7
        image_size = _number(data, info + 0x50, "<I")
        selectors = _slice(data, info + 0x58, 4)
        name_ptr = _number(data, info + 0x60, "<Q")
        mip_ptr = _number(data, info + 0x70, "<Q")
        if dimension != 2 or depth != 1 or layers != 1 or tile_mode not in (0, 1):
            raise UnsupportedTextureError("Only ordinary 2D BNTX textures are supported")
        kind = fmt >> 8
        bpp = {0x02: 1, 0x09: 2, 0x0B: 4, 0x1A: 8, 0x1B: 16,
               0x1C: 16, 0x1D: 8, 0x1E: 16, 0x20: 16}.get(kind)
        if bpp is None or fmt & 255 not in (1, 6):
            raise UnsupportedTextureError(f"Unsupported BNTX texture format 0x{fmt:04x}")
        block = 4 if kind >= 0x1A else 1
        blocks_x, blocks_y = (width + block - 1) // block, (height + block - 1) // block
        payload_ptr = _number(data, mip_ptr, "<Q")
        surface = deswizzle(_slice(data, payload_ptr, image_size), blocks_x, blocks_y,
                            bpp, block_height, linear=tile_mode == 1)
        rgba = _decode(surface, width, height, fmt)
        channels = (bytes(width * height), bytes([255]) * (width * height),
                    rgba[0::4], rgba[1::4], rgba[2::4], rgba[3::4])
        selected = bytearray(len(rgba))
        for c, selector in enumerate(selectors):
            selector = selector or c + 2
            if selector > 5:
                raise ValueError("Invalid BNTX channel selector")
            selected[c::4] = channels[selector]
        name_size = _number(data, name_ptr, "<H")
        name = _slice(data, name_ptr + 2, name_size).decode("utf-8")
        result.append(Texture(name, width, height, fmt, bytes(selected)))
    return result
