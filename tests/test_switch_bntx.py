"""Synthetic texture fixtures; no game or console key data is checked in."""
import struct

import pytest

from rae.platforms.switch.bntx import _decode_bc2, decode_bntx, deswizzle

pytestmark = pytest.mark.switch


def fixture_rgba():
    data = bytearray(0x600)
    data[:8] = b"BNTX\0\0\0\0"
    data[12:14] = b"\xff\xfe"
    data[32:36] = b"NX  "
    struct.pack_into("<IQ", data, 36, 1, 0x60)
    struct.pack_into("<Q", data, 0x60, 0x100)
    data[0x100:0x104] = b"BRTI"
    # Modern BRTI starts with flags, dimension, tile mode, NOT old tile mode.
    struct.pack_into("<BBH", data, 0x110, 9, 2, 0)
    struct.pack_into("<I", data, 0x11C, 0x0B01)
    struct.pack_into("<IIII", data, 0x124, 2, 2, 1, 1)
    struct.pack_into("<I", data, 0x150, 512)
    data[0x158:0x15C] = bytes((2, 3, 4, 5))
    struct.pack_into("<Q", data, 0x160, 0x90)
    struct.pack_into("<H4s", data, 0x90, 4, b"test")
    struct.pack_into("<Q", data, 0x170, 0x200)
    struct.pack_into("<Q", data, 0x200, 0x400)
    # Four independent known Tegra addresses for a 2x2 RGBA surface.
    for offset, color in ((0, (255, 0, 0, 255)), (4, (0, 255, 0, 255)),
                          (16, (0, 0, 255, 255)), (20, (255, 255, 255, 255))):
        data[0x400 + offset:0x404 + offset] = bytes(color)
    return data


def test_modern_brti_and_tegra_channel_order():
    texture, = decode_bntx(bytes(fixture_rgba()))
    assert (texture.name, texture.width, texture.height) == ("test", 2, 2)
    assert texture.rgba == bytes((255, 0, 0, 255, 0, 255, 0, 255,
                                  0, 0, 255, 255, 255, 255, 255, 255))


def test_texture_channel_remap_and_constants():
    data = fixture_rgba()
    data[0x158:0x15C] = bytes((4, 3, 2, 1))
    texture, = decode_bntx(bytes(data))
    assert texture.rgba[:4] == bytes((0, 0, 255, 255))


def test_bc2_keeps_explicit_alpha_and_four_color_mode():
    # Low c0 intentionally checks BC2's four-color rule, unlike BC1.
    data = struct.pack("<QHHI", 0xFEDCBA9876543210, 0x07E0, 0xF800, 2)
    rgba = _decode_bc2(data, 4, 4)
    assert rgba[:4] == bytes((85, 170, 0, 0))
    assert rgba[3::4] == bytes(range(0, 256, 17))


@pytest.mark.parametrize("offset,fmt,value", [
    (0x130, "<I", 2),       # arrays
    (0x124, "<I", 0),       # invalid dimensions
    (0x11C, "<I", 0x1D02),  # signed BC4 is not an unsigned channel
    (0x200, "<Q", 0x5FF),   # out-of-bounds image data
])
def test_unsupported_or_truncated_textures_fail_explicitly(offset, fmt, value):
    data = fixture_rgba()
    struct.pack_into(fmt, data, offset, value)
    with pytest.raises(ValueError):
        decode_bntx(bytes(data))


def test_pitch_linear_surface_and_truncation():
    row = bytes(range(8)) + bytes(24)
    assert deswizzle(row * 2, 2, 2, 4, 0, linear=True) == bytes(range(8)) * 2
    with pytest.raises(ValueError, match="bounds"):
        deswizzle(bytes(4), 2, 2, 4, 0)
