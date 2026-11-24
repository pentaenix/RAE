"""Nintendo DS sound archive tables and lossless sample extraction."""
from __future__ import annotations

import struct
from dataclasses import dataclass

from ...core.util import read_u16le, read_u32le

AUDIO_MAGICS: dict[bytes, tuple[str, str]] = {
    b"SDAT": ("Sound archive", ".sdat"),
    b"SSEQ": ("Sound sequence", ".sseq"),
    b"SSAR": ("Sound sequence archive / SFX", ".ssar"),
    b"SBNK": ("Sound bank / instruments", ".sbnk"),
    b"SWAR": ("Sound wave archive", ".swar"),
    b"SWAV": ("Sound wave sample", ".swav"),
    b"STRM": ("Sound stream", ".strm"),
}

AUDIO_EXTENSIONS = {ext for _kind, ext in AUDIO_MAGICS.values()}


@dataclass(slots=True)
class AudioEntry:
    path: str
    data: bytes
    offset: int
    size: int
    magic: str
    index: int


def find_section(data: bytes, name: bytes) -> tuple[int, bytes] | None:
    if len(data) < 16:
        return None
    offset = read_u16le(data, 12)
    if offset < 16:
        return None
    for _ in range(read_u16le(data, 14)):
        if offset + 8 > len(data):
            return None
        size = read_u32le(data, offset + 4)
        if size < 8 or offset + size > len(data):
            return None
        if data[offset:offset + 4] == name:
            return offset + 8, data[offset + 8:offset + size]
        offset += size
    return None


def _sdat_block(data: bytes, index: int, magic: bytes) -> memoryview:
    if not data.startswith(b"SDAT") or len(data) < 48:
        return memoryview(b"")
    offset, size = struct.unpack_from("<II", data, 16 + index * 8)
    if offset < 48 or size < 8 or offset + size > len(data) or data[offset:offset + 4] != magic:
        return memoryview(b"")
    return memoryview(data)[offset:offset + size]


def _file_table(data: bytes) -> tuple[memoryview, int, int]:
    fat = _sdat_block(data, 2, b"FAT ")
    file = _sdat_block(data, 3, b"FILE")
    if len(fat) < 12 or len(file) < 12:
        return memoryview(b""), 0, 0
    start = read_u32le(data, 40)
    end = 12 + read_u32le(fat, 8) * 16
    return (fat[12:end], start + 12, start + len(file)) if end <= len(fat) else (memoryview(b""), 0, 0)


def _sdat_entry(data: bytes, fat: memoryview, start: int, end: int, index: int) -> AudioEntry | None:
    if not 0 <= index < len(fat) // 16:
        return None
    offset, size = struct.unpack_from("<II", fat, index * 16)
    if not size or offset < start or offset + size > end:
        return None
    raw = data[offset:offset + size]
    magic = raw[:4].decode("ascii") if raw[:4] in AUDIO_MAGICS else "BIN"
    ext = AUDIO_MAGICS.get(raw[:4], ("Binary", ".bin"))[1]
    return AudioEntry(f"sdat_{index:04d}_{magic.lower()}{ext}", raw, offset, size, magic, index)


def get_sdat_file(data: bytes, index: int) -> AudioEntry | None:
    return _sdat_entry(data, *_file_table(data), index)


def iter_sdat_files(data: bytes) -> list[AudioEntry]:
    fat, start, end = _file_table(data)
    return [entry for index in range(len(fat) // 16)
            if (entry := _sdat_entry(data, fat, start, end, index)) is not None]


def iter_swar_swavs(data: bytes) -> list[AudioEntry]:
    section = find_section(data, b"DATA") if data.startswith(b"SWAR") else None
    if section is None:
        return []
    start, payload = section
    if len(payload) < 36:
        return []
    count = read_u32le(payload, 32)
    end = start + len(payload)
    table_end = start + 36 + count * 4
    if table_end > end:
        return []
    entries = []
    for index in range(count):
        offset = read_u32le(data, start + 36 + index * 4)
        if not table_end <= offset <= end - 12:
            continue
        _, _, _, _, loop_words, tail_words = struct.unpack_from("<BBHHHI", data, offset)
        size = 12 + (loop_words + tail_words) * 4
        if offset + size > end or size <= 12 or data[offset] > 2:
            continue
        # SWAR stores bare wave records. Wrap each record in a valid SWAV.
        header = struct.pack("<4sHHIHH4sI", b"SWAV", 0xfeff, 0x100,
                             24 + size, 16, 1, b"DATA", 8 + size)
        entries.append(AudioEntry(f"swar_{index:04d}.swav", header + data[offset:offset + size],
                                  offset, size, "SWAV", index))
    return entries


def _table(block: memoryview, index: int) -> list[int]:
    start = 8 + index * 4
    if len(block) < start + 4:
        return []
    offset = read_u32le(block, start)
    return [row[0] for row in _offset_rows(block, offset, 1)]


def _offset_rows(block: memoryview, offset: int, columns: int) -> list[tuple[int, ...]]:
    if not 8 <= offset <= len(block) - 4:
        return []
    count = read_u32le(block, offset)
    end = offset + 4 + count * columns * 4
    if end > len(block):
        return []
    return list(struct.iter_unpack("<" + "I" * columns, block[offset + 4:end]))


def sdat_sound_symbols(data: bytes) -> list[dict]:
    """Map SDAT symbols to their INFO index and physical file ID."""
    symbols = _sdat_block(data, 0, b"SYMB")
    info = _sdat_block(data, 1, b"INFO")
    names = bytes(symbols)

    def name_at(offset: int, fallback: str) -> str:
        end = names.find(b"\0", offset) if 8 <= offset < len(names) else -1
        return names[offset:end].decode("ascii", errors="replace") if end > offset else fallback

    sounds = []
    for index, magic in ((0, "SSEQ"), (3, "SWAR"), (7, "STRM")):
        offsets = _table(symbols, index)
        for number, record in enumerate(_table(info, index)):
            if not 8 <= record <= len(info) - 2:
                continue
            offset = offsets[number] if number < len(offsets) else 0
            sounds.append({"name": name_at(offset, f"{magic}_{number:04d}"),
                           "kind": magic, "index": number, "fileId": read_u16le(info, record)})

    archive_symbols = _offset_rows(symbols, read_u32le(symbols, 12), 2)
    for number, record in enumerate(_table(info, 1)):
        if not 8 <= record <= len(info) - 2:
            continue
        file_id = read_u16le(info, record)
        entry = get_sdat_file(data, file_id)
        if entry is None or entry.magic != "SSAR":
            continue
        section = find_section(entry.data, b"DATA")
        if section is None or len(section[1]) < 8:
            continue
        payload = section[1]
        start, count = struct.unpack_from("<II", payload)
        if not section[0] + 8 + count * 12 <= start <= section[0] + len(payload):
            continue
        title, subtable = archive_symbols[number] if number < len(archive_symbols) else (0, 0)
        archive_name = name_at(title, f"SSAR_{number:04d}")
        subnames = _offset_rows(symbols, subtable, 1)
        for index in range(count):
            offset = read_u32le(payload, 8 + index * 12)
            if start + offset >= section[0] + len(payload):
                continue
            name = subnames[index][0] if index < len(subnames) else 0
            sounds.append({"name": name_at(name, f"{archive_name}_{index:04d}"),
                           "kind": "SSAR", "archiveIndex": number, "archiveName": archive_name,
                           "index": index, "fileId": file_id})
    return sounds
