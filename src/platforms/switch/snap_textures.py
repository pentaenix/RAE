"""Decode the 2D NUTEXB color, normal and shadow maps used by Snap previews."""
from __future__ import annotations

import struct
from io import BytesIO

import numpy as np
from PIL import Image

from .bntx import _decode, deswizzle

# NUTEXB uses its own format IDs for the same BC surfaces as BNTX.
_BC6_UNSIGNED = 0x04D7
_FORMATS = {0x0480: (8, 0x1A01), 0x0485: (8, 0x1A06),
            0x04A0: (16, 0x1C01), 0x04A5: (16, 0x1C06), 0x0280: (16, 0x1E01),
            _BC6_UNSIGNED: (16, None)}


def decode_nutexb(data: bytes) -> Image.Image:
    if len(data) < 112 or data[-112:-108] != b" XNT" or data[-8:-4] != b" XET":
        raise ValueError("Missing Snap NUTEXB footer")
    width, height, depth, fmt, _, mips, layout, layers, size = struct.unpack_from("<9I", data, len(data) - 44)
    if depth != 1 or layers != 1 or layout not in (0, 0x1000) or not 1 <= mips <= 16:
        raise ValueError("Unsupported Snap NUTEXB surface")
    if not (0 < width <= 4096 and 0 < height <= 4096 and size <= len(data) - 112):
        raise ValueError("Invalid Snap NUTEXB dimensions or data size")
    if fmt not in _FORMATS:
        raise ValueError(f"Unsupported Snap NUTEXB format {fmt:#06x}")
    block_size, bntx_format = _FORMATS[fmt]
    blocks_x, blocks_y = (width + 3) // 4, (height + 3) // 4
    if layout:
        # Derive mip-0 GOB height using the Tegra texture tiling rule.
        padded_height = blocks_y + blocks_y // 2
        height_log2 = min(4, max(0, (padded_height // 8).bit_length() - 1))
        surface = deswizzle(data[:size], blocks_x, blocks_y, block_size, height_log2)
    else:
        length = blocks_x * blocks_y * block_size
        if length > size:
            raise ValueError("Truncated Snap NUTEXB mip")
        surface = data[:length]
    if fmt == _BC6_UNSIGNED:
        from texture2ddecoder import decode_bc6

        return Image.frombytes("RGBA", (width, height), decode_bc6(surface, width, height), "raw", "BGRA")
    return Image.frombytes("RGBA", (width, height), _decode(surface, width, height, bntx_format))


def texture_png(data: bytes, role: str, *, size_limit: int | None = None) -> bytes:
    image = decode_nutexb(data)
    if size_limit is not None:
        image.thumbnail((size_limit, size_limit), Image.Resampling.LANCZOS)
    if role == "normal":
        # BC5 stores tangent-space X/Y. Reconstruct the positive Z hemisphere.
        rgb = np.asarray(image.convert("RGB")).copy()
        xy = rgb[:, :, :2].astype(np.float32) / 127.5 - 1
        z = np.sqrt(np.maximum(0, 1 - np.sum(xy * xy, axis=2)))
        rgb[:, :, 2] = np.rint((z + 1) * 127.5).astype(np.uint8)
        image = Image.fromarray(rgb)
    elif role == "shadow":
        # The source texture is a black overlay whose alpha is shadow strength.
        # glTF occlusion instead uses red = 1 for unoccluded texels.
        image = image.getchannel("A").point([255 - alpha for alpha in range(256)])
    elif role != "cutout":
        image = image.convert("RGB")
    output = BytesIO()
    image.save(output, "PNG", compress_level=3)
    return output.getvalue()
