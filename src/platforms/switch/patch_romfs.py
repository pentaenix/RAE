"""Random-access base + update RomFS overlay (NCA AES-CTR-Ex/BKTR).

Format references: Switchbrew NCA and SciresM/hactool bktr.h/nca.c. The
original containers remain read-only; no decrypted full-game copy is needed.
"""
from __future__ import annotations

from bisect import bisect_right
from dataclasses import replace
from pathlib import Path
import struct
import threading

from .container import SwitchContainerError, SwitchRom, _ctr_decrypt, parse_romfs


def parse_buckets(data: bytes, record: str) -> tuple[int, list[tuple]]:
    """Flatten bounded BKTR leaf buckets, retaining the top-level end sentinel."""
    if len(data) < 0x4000:
        raise SwitchContainerError("Truncated BKTR tree")
    _, count, end = struct.unpack_from("<IIQ", data)
    if not 0 < count <= 0x7FE or (count + 1) * 0x4000 > len(data):
        raise SwitchContainerError("Invalid BKTR bucket count")
    stride = struct.calcsize(record)
    rows = []
    for bucket in range(count):
        start = (bucket + 1) * 0x4000
        _, size, bucket_end = struct.unpack_from("<IIQ", data, start)
        if size > 0x3FF0 // stride or bucket_end > end:
            raise SwitchContainerError("Invalid BKTR leaf size")
        rows.extend(struct.unpack_from(record, data, start + 16 + i * stride) for i in range(size))
    offsets = [row[0] for row in rows]
    if not offsets or offsets[0] != 0 or any(a >= b for a, b in zip(offsets, offsets[1:])) or offsets[-1] >= end:
        raise SwitchContainerError("Invalid BKTR interval order")
    return end, rows


class BktrSection:
    def __init__(self, base_nca, base_section, patch_nca, patch_section):
        self.base_nca, self.base_section = base_nca, base_section
        self.nca, self.section = patch_nca, patch_section
        self.lock = threading.RLock()
        info = patch_section.patch_info
        if len(info) != 64 or info[16:20] != b"BKTR" or info[48:52] != b"BKTR":
            raise SwitchContainerError("Missing BKTR patch metadata")
        reloc_offset, reloc_size = struct.unpack_from("<QQ", info)
        sub_offset, sub_size = struct.unpack_from("<QQ", info, 32)
        for offset, size in ((reloc_offset, reloc_size), (sub_offset, sub_size)):
            if size > 64 * 1024 * 1024 or offset + size > patch_section.media_size:
                raise SwitchContainerError("BKTR metadata exceeds its section")
        plain_ctr = replace(patch_section, crypto_type=3)
        self.size, self.relocations = parse_buckets(patch_nca.read_section(plain_ctr, reloc_offset, reloc_size), "<QQI")
        self.physical_size, self.subsections = parse_buckets(patch_nca.read_section(plain_ctr, sub_offset, sub_size), "<QII")
        if any(row[2] not in (0, 1) for row in self.relocations):
            raise SwitchContainerError("Invalid BKTR source selector")
        self.relocation_offsets = [r[0] for r in self.relocations] + [self.size]
        self.subsection_offsets = [r[0] for r in self.subsections] + [self.physical_size]

    def _read_patch(self, offset: int, size: int) -> bytes:
        out = bytearray()
        while size:
            index = bisect_right(self.subsection_offsets, offset) - 1
            if index < 0 or index >= len(self.subsections):
                raise SwitchContainerError("Patch read outside BKTR subsections")
            want = min(size, self.subsection_offsets[index + 1] - offset)
            nca_offset = self.section.media_offset - self.nca._base + offset
            pad = nca_offset & 15
            self.nca._fh.seek(self.section.media_offset + offset - pad)
            raw = self.nca._fh.read(want + pad)
            counter = (self.section.ctr_prefix[::-1][:4] + self.subsections[index][2].to_bytes(4, "big")
                       + ((nca_offset - pad) >> 4).to_bytes(8, "big"))
            if len(raw) != want + pad:
                raise SwitchContainerError("Truncated BKTR payload")
            out.extend(_ctr_decrypt(raw, self.section.key, counter)[pad:])
            offset += want
            size -= want
        return bytes(out)

    def read_section(self, section, offset: int, size: int) -> bytes:
        if offset < 0 or size < 0 or offset + size > self.size:
            raise SwitchContainerError("Read exceeds virtual BKTR image")
        out = bytearray()
        with self.lock:
            while size:
                index = bisect_right(self.relocation_offsets, offset) - 1
                virtual, physical, patch = self.relocations[index]
                want = min(size, self.relocation_offsets[index + 1] - offset)
                source = physical + offset - virtual
                if patch:
                    chunk = self._read_patch(source, want)
                else:
                    if source + want > self.base_section.media_size:
                        raise SwitchContainerError("Relocation exceeds base RomFS section")
                    chunk = self.base_nca.read_section(self.base_section, source, want)
                if len(chunk) != want:
                    raise SwitchContainerError("Truncated relocated RomFS read")
                out.extend(chunk)
                offset += want
                size -= want
        return bytes(out)


class PatchedSwitchRom:
    """SwitchRom-compatible merged view, safe for concurrent archive reads."""
    def __init__(self, base: str | Path, update: str | Path):
        self.base = SwitchRom(base)
        self.patch = SwitchRom(update, allow_patch=True)
        try:
            self.base._load_program()
            self.patch._load_program()
            bn, pn = self.base._program_nca, self.patch._program_nca
            bs, ps = self.base._romfs_section, self.patch._romfs_section
            if bn.title_id != pn.title_id:
                raise SwitchContainerError("Update title does not match the base game")
            if ps.crypto_type != 4:
                raise SwitchContainerError("Update is not a BKTR RomFS patch")
            self.section = ps
            self.view = BktrSection(bn, bs, pn, ps)
            self._files = None
        except Exception:
            self.close()
            raise

    def romfs_files(self):
        if self._files is None:
            self._files = parse_romfs(self.view, self.section)
        return self._files

    def read_file(self, entry, offset=0, size=None):
        if offset < 0 or offset > entry.size or (size is not None and size < 0):
            raise SwitchContainerError("Invalid RomFS file range")
        want = entry.size - offset if size is None else min(size, entry.size - offset)
        return self.view.read_section(self.section, entry.offset + offset, want)

    def close(self):
        self.base.close()
        self.patch.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
