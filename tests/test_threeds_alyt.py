"""Synthetic named layout archives: endian handling and strict offset bounds."""
import struct
import pytest

from rae.platforms.threeds.alyt import read_alyt_files, read_sarc_files

pytestmark = pytest.mark.threeds


def archive(endian="<"):
    data = bytearray(132)
    data[:4] = b"SARC"
    struct.pack_into(endian + "HHIIHH", data, 4, 20, 0xFEFF, len(data), 128, 0x100, 0)
    data[20:24] = b"SFAT"
    struct.pack_into(endian + "HHI", data, 24, 12, 1, 0x65)
    struct.pack_into(endian + "IIII", data, 32, 0, 0x1000000, 0, 4)
    data[48:52] = b"SFNT"
    struct.pack_into(endian + "HH", data, 52, 8, 0)
    name = b"timg/Mark_01.bflim\0"
    data[56:56 + len(name)] = name
    data[128:132] = b"test"
    return data


@pytest.mark.parametrize("endian", ["<", ">"])
def test_layout_preserves_named_payload_exactly(endian):
    wrapped = b"ALYT" + bytes(36) + bytes(24) + archive(endian)
    files = read_alyt_files(wrapped)
    assert [(f.name, f.data) for f in files] == [("timg/Mark_01.bflim", b"test")]


def test_entry_cannot_read_past_sarc_size():
    data = archive()
    struct.pack_into("<I", data, 44, 5)
    with pytest.raises(ValueError, match="entry exceeds"):
        read_sarc_files(data)


def test_names_cannot_point_into_texture_data():
    data = archive()
    struct.pack_into("<I", data, 36, 0x1000012)
    with pytest.raises(ValueError, match="invalid name offset"):
        read_sarc_files(data)


def test_header_rejects_truncated_archive_and_missing_layout():
    with pytest.raises(ValueError, match="file bounds"):
        read_sarc_files(archive()[:-1])
    with pytest.raises(ValueError, match="ALYT"):
        read_alyt_files(b"bad")
    with pytest.raises(ValueError, match="no embedded SARC"):
        read_alyt_files(b"ALYT" + bytes(36))
