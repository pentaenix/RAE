"""GFPAK tests use wholly synthetic model/animation payloads."""
import struct

import lz4.block
import pytest

from rae.platforms.switch.fnv import fnv1a64
from rae.platforms.switch.gfpak import read_gfpak

pytestmark=pytest.mark.switch


def pack(codec=2,duplicate=False):
    source=[b'synthetic model'*9,b'synthetic walk animation'*8]
    payload=[lz4.block.compress(p,store_size=False) for p in source]
    data=bytearray(144)
    data[:8]=b'GFLXPACK'
    struct.pack_into('<IIIIQQQ',data,8,0x1000,0,2,1,96,48,64)
    struct.pack_into('<QQ',data,48,111,222)
    struct.pack_into('<QII',data,64,333,2,0xCC)
    for i,name in enumerate(('model.gfbmdl','walk.gfbanm')):
        struct.pack_into('<QII',data,80+i*16,fnv1a64(name),0 if duplicate else i,0xCC)
    # The second folder file record ends at 112, so put the table after it.
    struct.pack_into('<Q',data,24,112)
    data.extend(b'\0'*16)
    for i,(raw,compressed) in enumerate(zip(source,payload)):
        struct.pack_into('<HHIIIQ',data,112+i*24,9,codec,len(raw),len(compressed),0xCC,len(data))
        data.extend(compressed)
    return bytes(data),source


def test_lz4_payload_and_both_filename_hashes_survive():
    data,source=pack();files=read_gfpak(data)
    assert [f.data for f in files]==source
    assert files[1].name_hash==fnv1a64('walk.gfbanm')
    assert files[1].absolute_hash==222


def test_duplicate_index_unknown_codec_and_truncation_are_rejected():
    with pytest.raises(ValueError,match='Duplicate'):
        read_gfpak(pack(duplicate=True)[0])
    with pytest.raises(ValueError,match='codec'):
        read_gfpak(pack(codec=99)[0])
    with pytest.raises(ValueError,match='bounds'):
        read_gfpak(pack()[0][:-2])
