"""Read common NSP ticket keys into memory; never modify console key files."""
from __future__ import annotations

import struct

from .keys import SwitchKeyError, SwitchKeys

_BODY_OFFSETS = {0x10000: 0x240, 0x10003: 0x240, 0x10001: 0x140,
                 0x10004: 0x140, 0x10002: 0x80, 0x10005: 0x80, 0x10006: 0x40}


def load_common_tickets(fh, entries, keys: SwitchKeys) -> SwitchKeys:
    """Return a private key set supplemented by tickets in this container.

    Personalized RSA tickets require console-specific conversion and are skipped;
    an explicit user-provided title key can still satisfy those NCAs.
    """
    result = SwitchKeys(raw=dict(keys.raw), source=keys.source)
    for entry in entries:
        if not entry.name.lower().endswith(".tik"):
            continue
        if entry.size > 0x10000:
            raise SwitchKeyError("NSP ticket exceeds the supported size")
        fh.seek(entry.offset)
        data = fh.read(entry.size)
        if len(data) < 4:
            raise SwitchKeyError("Truncated NSP ticket")
        body = _BODY_OFFSETS.get(struct.unpack_from("<I", data)[0])
        if body is None or len(data) < body + 0x170:
            raise SwitchKeyError("Unsupported or truncated NSP ticket signature")
        if data[body + 0x141] != 0:
            continue
        rights = data[body + 0x160:body + 0x170]
        if any(rights):
            result.raw.setdefault("titlekey_" + rights.hex(), data[body + 0x40:body + 0x50])
    return result
