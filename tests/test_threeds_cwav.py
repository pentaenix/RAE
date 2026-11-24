import struct
import numpy as np
import pytest
from rae.platforms.threeds.audio_module.cwav import dsp_pcm, decode, metadata

pytestmark=pytest.mark.threeds


def test_dsp_signed_nibbles_and_scale():
    data=bytes([1,0x17,0x8f,0x02,0x34,0x56,0x70,0x98])
    np.testing.assert_array_equal(dsp_pcm(data,[0]*16,14),[2,14,-16,-2,0,4,6,8,10,12,14,0,-14,-16])


def test_dsp_history_rounding_and_saturation():
    # Unit predictor accumulates positive deltas, saturating rather than wrapping.
    data=bytes([15]+[0x77]*7)*2
    out=dsp_pcm(data,[2048,0]+[0]*14,28)
    assert (out==32767).all()
    with pytest.raises(ValueError,match='predictor'):dsp_pcm(bytes([0x80]+[0]*7),[0]*16,14)
    with pytest.raises(ValueError,match='Truncated'):dsp_pcm(b'\0'*7,[0]*16,14)


def test_pcm16_channel_offsets_and_metadata():
    data=bytearray(160)
    data[:6]=b'CWAV\xff\xfe'
    for at,value in [(12,160),(24,64),(36,128),(68,64),(76,32000),(80,0),(84,4),(92,1),(100,12),(108,0)]:
        struct.pack_into('<I',data,at,value)
    data[64:68]=b'INFO';data[72]=1;data[73]=1
    data[128:132]=b'DATA';struct.pack_into('<4h',data,136,10,-20,30,-40)
    pcm,meta=decode(bytes(data))
    np.testing.assert_array_equal(pcm[:,0],[10,-20,30,-40])
    assert meta['loop'] and meta['rate']==32000
    data[12]=0
    with pytest.raises(ValueError,match='size'):metadata(bytes(data))
