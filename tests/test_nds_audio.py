import struct

import pytest

from rae.platforms.nds.audio_archives import get_sdat_file, iter_sdat_files, iter_swar_swavs
from rae.platforms.nds.audio_pcm import decode_strm_pcm, decode_swav_pcm


pytestmark = pytest.mark.nds


def nitro(magic, *sections):
    body = b"".join(tag + struct.pack("<I", len(payload) + 8) + payload for tag, payload in sections)
    return struct.pack("<4sHHIHH", magic, 0xFEFF, 0x100, 16 + len(body), 16, len(sections)) + body


def test_swar_contains_bare_wave_and_signed_pcm8():
    samples = bytes((0x80, 0xFF, 0, 0x7F))
    record = struct.pack("<BBHHHI", 0, 0, 16000, 0, 0, 1) + samples
    data = nitro(b"SWAR", (b"DATA", bytes(32) + struct.pack("<II", 1, 64) + record))
    wave, = iter_swar_swavs(data)
    assert wave.offset == 64 and wave.index == 0
    assert decode_swav_pcm(wave.data) == (16000, 1, 1, bytes((0, 127, 128, 255)))
    assert iter_swar_swavs(data[:-2]) == []


def test_sdat_fat_offsets_are_absolute_even_when_both_offsets_fit():
    fat_offset, file_offset, sample_offset = 64, 92, 108
    data = bytearray(512)
    struct.pack_into("<4sHHIHH8I", data, 0, b"SDAT", 0xFEFF, 0x100, len(data),
                     64, 2, 0, 0, 0, 0, fat_offset, 28, file_offset, 420)
    struct.pack_into("<4sIII", data, fat_offset, b"FAT ", 28, 1, sample_offset)
    struct.pack_into("<I", data, fat_offset + 16, 4)
    struct.pack_into("<4sII", data, file_offset, b"FILE", 420, 1)
    data[sample_offset:sample_offset + 4] = b"SSEQ"
    entry, = iter_sdat_files(bytes(data))
    assert entry == get_sdat_file(bytes(data), 0)
    assert entry.offset == sample_offset and entry.data == b"SSEQ"


def test_adpcm_seed_sets_predictor_without_adding_a_sample():
    record = struct.pack("<BBHHHIhH", 2, 0, 16000, 0, 0, 2, 100, 0) + b"\x11" * 4
    pcm = decode_swav_pcm(nitro(b"SWAV", (b"DATA", record)))
    assert pcm[:3] == (16000, 1, 2)
    assert struct.unpack("<8h", pcm[3]) == tuple(range(101, 109))


def test_strm_interleaves_channels_and_honors_final_block_size():
    header = struct.pack("<BBBBHH8I", 1, 0, 2, 0, 32728, 0, 0, 3, 72, 2, 4, 2, 2, 1)
    payload = struct.pack("<6h", 10, 20, 100, 200, 30, 300)
    data = nitro(b"STRM", (b"HEAD", header), (b"DATA", payload))
    assert decode_strm_pcm(data) == (32728, 2, 2, struct.pack("<6h", 10, 100, 20, 200, 30, 300))
    assert decode_strm_pcm(data[:-1]) is None
