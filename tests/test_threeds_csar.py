"""Tiny synthetic CSAR→CBNK→CWAR→CWAV proof; no ROM fixture is required."""
import struct
import pytest
from rae.platforms.threeds.audio_module.csar import SoundArchive
from rae.platforms.threeds.audio_module.cwav import decode

pytestmark=pytest.mark.threeds


def fixture():
    b=bytearray(2048)
    def put(at,*values):struct.pack_into('<'+'I'*len(values),b,at,*values)
    b[:6]=b'CSAR\xff\xfe';put(12,len(b));struct.pack_into('<H',b,16,3)
    for i,(at,size) in enumerate([(64,192),(256,512),(768,1280)]):put(20+i*12,0x2000+i,at,size)
    b[64:68]=b'STRG';put(76,16);put(88,1,0x1f01,16,13);b[104:117]=b'BANK_SE_TEST\0'
    b[256:260]=b'INFO';put(264+2*8,0x2101,96);put(264+3*8,0x2103,184);put(264+6*8,0x2106,248)
    put(360,1,0x2206,12);put(372,0,0x100,20,1,0,0)
    put(448,1,0x2207,12);put(460,1,1,0,0,0)
    put(512,2,0x220a,20,0x220a,44)
    put(532,0x220c,12,0,0x1f00,0,80);put(556,0x220c,12,0,0x1f00,80,288)
    b[768:772]=b'FILE'
    base=776;b[base:base+6]=b'CBNK\xff\xfe';put(base+12,80);put(base+24,32)
    b[base+32:base+36]=b'INFO';put(base+40,0x100,16);put(base+56,1,0x05000000,0)
    arc=856;b[arc:arc+6]=b'CWAR\xff\xfe';put(arc+12,288);put(arc+24,64);put(arc+36,96)
    b[arc+64:arc+68]=b'INFO';put(arc+72,1,0x1f00,24,160);b[arc+96:arc+100]=b'FILE'
    wave=arc+128;b[wave:wave+6]=b'CWAV\xff\xfe';put(wave+12,160);put(wave+24,64);put(wave+36,128)
    b[wave+64:wave+68]=b'INFO';b[wave+72]=1;put(wave+76,32000,0,4);put(wave+92,1);put(wave+100,12)
    b[wave+128:wave+132]=b'DATA';struct.pack_into('<4h',b,wave+136,17,-29,41,-53)
    return b


def test_bank_references_name_and_exact_embedded_wave():
    waves=list(SoundArchive(bytes(fixture())).bank_waves())
    assert len(waves)==1
    wave=waves[0]
    assert (wave.bank,wave.archive_id,wave.wave_index,wave.offset)==('BANK_SE_TEST',0,0,984)
    pcm,meta=decode(wave.data)
    assert pcm[:,0].tolist()==[17,-29,41,-53] and meta['rate']==32000


def test_wave_archive_and_file_bounds_are_not_guessed():
    b=fixture();struct.pack_into('<I',b,776+60,0x05000003)
    with pytest.raises(ValueError,match='table index'):list(SoundArchive(bytes(b)).bank_waves())
    b=fixture();struct.pack_into('<I',b,532+20,4096)
    with pytest.raises(ValueError,match='file exceeds'):list(SoundArchive(bytes(b)).bank_waves())
