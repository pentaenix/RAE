"""Synthetic ticket and BKTR fixtures; no console key material or ROM required."""
import io
import struct
from types import SimpleNamespace

from Crypto.Cipher import AES
import pytest

from rae.platforms.switch.container import NcaSection, PartitionEntry, SwitchContainerError
from rae.platforms.switch.keys import SwitchKeys, SwitchKeyError
from rae.platforms.switch.patch_romfs import BktrSection, parse_buckets
from rae.platforms.switch.tickets import load_common_tickets

pytestmark = pytest.mark.switch


def ticket(kind=0):
    data = bytearray(0x400)
    struct.pack_into("<I", data, 0, 0x10004)
    data[0x180:0x190] = bytes(range(16))
    data[0x281] = kind
    data[0x2A0:0x2B0] = bytes(range(16,32))
    return bytes(data)


def test_common_ticket_is_private_and_personalized_is_not_misread():
    keys = SwitchKeys(raw={"existing": b"test"})
    entry = PartitionEntry("ticket.tik", 0, 0x400)
    result = load_common_tickets(io.BytesIO(ticket()), [entry], keys)
    assert len(result.raw) == 2 and len(keys.raw) == 1
    assert result.raw["titlekey_" + bytes(range(16,32)).hex()] == bytes(range(16))
    assert load_common_tickets(io.BytesIO(ticket(1)), [entry], keys).raw == keys.raw
    with pytest.raises(SwitchKeyError, match="Truncated"):
        load_common_tickets(io.BytesIO(b"bad"), [PartitionEntry("x.tik",0,3)], keys)


def tree(rows, fmt, end):
    data = bytearray(0x8000)
    struct.pack_into("<IIQ", data, 0, 0, 1, end)
    struct.pack_into("<IIQ", data, 0x4000, 0, len(rows), end)
    for i,row in enumerate(rows):
        struct.pack_into(fmt, data, 0x4010 + i*struct.calcsize(fmt), *row)
    return bytes(data)


def test_bucket_bounds_and_monotonic_intervals():
    assert parse_buckets(tree([(0,0,0),(16,8,1)],"<QQI",32),"<QQI")[0] == 32
    with pytest.raises(SwitchContainerError, match="order"):
        parse_buckets(tree([(1,0,0)],"<QQI",32),"<QQI")
    with pytest.raises(SwitchContainerError, match="Truncated"):
        parse_buckets(b"short","<QQI")


def test_overlay_splits_relocations_and_crypto_subsections_at_unaligned_reads():
    key = bytes(range(16))  # Synthetic AES test key, unrelated to any console.
    prefix = bytes(range(8))
    plain = bytes(range(64))
    encrypted = bytearray()
    for start,end,generation in ((0,32,7),(32,64,9)):
        iv = prefix[::-1][:4] + generation.to_bytes(4,"big") + ((0x4000+start)>>4).to_bytes(8,"big")
        encrypted.extend(AES.new(key,AES.MODE_CTR,nonce=b"",initial_value=int.from_bytes(iv,"big")).encrypt(plain[start:end]))
    reloc = tree([(0,0,0),(8,8,1),(48,48,0)],"<QQI",64)
    subs = tree([(0,0,7),(32,0,9)],"<QII",64)
    info = bytearray(64)
    struct.pack_into("<QQ4s",info,0,128,len(reloc),b"BKTR")
    struct.pack_into("<QQ4s",info,32,128+len(reloc),len(subs),b"BKTR")
    patch_section = NcaSection(1,0x4000,128+len(reloc)+len(subs),0,4,prefix,key,patch_info=bytes(info))
    def physical(section,offset,size):
        return {128:reloc,128+len(reloc):subs}[offset][:size]
    patch = SimpleNamespace(_base=0,_fh=io.BytesIO(b"\0"*0x4000+encrypted),read_section=physical)
    base = SimpleNamespace(read_section=lambda section,offset,size:b"B"*size)
    overlay = BktrSection(base,SimpleNamespace(media_size=64),patch,patch_section)
    assert overlay.read_section(patch_section,3,55) == b"B"*5+plain[8:48]+b"B"*10
    with pytest.raises(SwitchContainerError,match="exceeds"):
        overlay.read_section(patch_section,63,2)
