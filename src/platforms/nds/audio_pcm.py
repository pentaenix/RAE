"""Decode Nitro samples and streams to WAV-compatible PCM."""
from __future__ import annotations

import struct

from .audio_archives import find_section

Pcm = tuple[int, int, int, bytes]
_SIGNED_TO_UNSIGNED = bytes(value ^ 0x80 for value in range(256))


def _decode_channel(codec: int, raw: bytes) -> tuple[int, bytes]:
    if codec == 0:
        return 1, raw.translate(_SIGNED_TO_UNSIGNED)
    if codec == 1 and len(raw) % 2 == 0:
        return 2, raw
    if codec == 2 and len(raw) > 4:
        return 2, decode_ds_ima_adpcm(raw)
    return 0, b""


def decode_swav_pcm(data: bytes) -> Pcm | None:
    section = find_section(data, b"DATA") if data.startswith(b"SWAV") else None
    if section is None or len(section[1]) < 12:
        return None
    _, payload = section
    codec, _, rate, _, loop_words, tail_words = struct.unpack_from("<BBHHHI", payload)
    size = (loop_words + tail_words) * 4
    if not rate or size > len(payload) - 12:
        return None
    width, samples = _decode_channel(codec, payload[12:12 + size])
    return (rate, 1, width, samples) if samples else None


def decode_strm_pcm(data: bytes) -> Pcm | None:
    head = find_section(data, b"HEAD") if data.startswith(b"STRM") else None
    section = find_section(data, b"DATA") if head else None
    if head is None or section is None or len(head[1]) < 40:
        return None
    h = head[1]
    codec, _, channels, _, rate = struct.unpack_from("<BBBBH", h)
    frames, offset, blocks, block_bytes, block_frames, last_bytes, last_frames = struct.unpack_from("<7I", h, 12)
    payload_start, payload = section
    if not (codec in (0, 1, 2) and 1 <= channels <= 2 and rate and frames and blocks and
            offset >= payload_start and blocks <= frames and
            frames == (blocks - 1) * block_frames + last_frames):
        return None
    cursor = offset - payload_start
    if cursor + channels * ((blocks - 1) * block_bytes + last_bytes) > len(payload):
        return None
    output = bytearray()
    width = 1 if codec == 0 else 2
    for block in range(blocks):
        final = block == blocks - 1
        size = last_bytes if final else block_bytes
        required = (last_frames if final else block_frames) * width
        decoded = []
        for _ in range(channels):
            _, samples = _decode_channel(codec, payload[cursor:cursor + size])
            if len(samples) < required:
                return None
            decoded.append(samples[:required])
            cursor += size
        if channels == 1:
            output.extend(decoded[0])
        else:
            interleaved = bytearray(required * channels)
            for byte_index in range(width):
                for channel, samples in enumerate(decoded):
                    interleaved[channel * width + byte_index::channels * width] = samples[byte_index::width]
            output.extend(interleaved)
    return rate, channels, width, bytes(output)


def decode_ds_ima_adpcm(raw: bytes) -> bytes:
    index_table = [-1, -1, -1, -1, 2, 4, 6, 8, -1, -1, -1, -1, 2, 4, 6, 8]
    step_table = [
        7, 8, 9, 10, 11, 12, 13, 14, 16, 17, 19, 21, 23, 25, 28, 31,
        34, 37, 41, 45, 50, 55, 60, 66, 73, 80, 88, 97, 107, 118, 130,
        143, 157, 173, 190, 209, 230, 253, 279, 307, 337, 371, 408, 449,
        494, 544, 598, 658, 724, 796, 876, 963, 1060, 1166, 1282, 1411,
        1552, 1707, 1878, 2066, 2272, 2499, 2749, 3024, 3327, 3660, 4026,
        4428, 4871, 5358, 5894, 6484, 7132, 7845, 8630, 9493, 10442,
        11487, 12635, 13899, 15289, 16818, 18500, 20350, 22385, 24623,
        27086, 29794, 32767,
    ]
    if len(raw) < 4:
        return b""
    predictor = struct.unpack_from("<h", raw, 0)[0]
    index = min(88, raw[2] & 0x7f)
    out = bytearray()
    for byte in raw[4:]:
        for nibble in (byte & 0x0F, byte >> 4):
            step = step_table[index]
            diff = step >> 3
            if nibble & 1:
                diff += step >> 2
            if nibble & 2:
                diff += step >> 1
            if nibble & 4:
                diff += step
            predictor = predictor - diff if nibble & 8 else predictor + diff
            predictor = max(-32767, min(32767, predictor))
            index = max(0, min(88, index + index_table[nibble]))
            out.extend(struct.pack("<h", predictor))
    return bytes(out)
