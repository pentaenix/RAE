"""Bounded NintendoWare CWAV metadata and PCM/DSP decoding (3DS only).

Format cross-checks (primary implementation):
https://github.com/vgmstream/vgmstream/blob/master/src/meta/bfwav.c
https://github.com/vgmstream/vgmstream/blob/master/src/coding/ngc_dsp_decoder.c
No keys, synthesizer, playback device, or another platform module is involved.
"""
from __future__ import annotations
import struct
import numpy as np


def dsp_pcm(data: bytes, coefficients, count: int) -> np.ndarray:
    if count<0 or (count+13)//14*8>len(data):
        raise ValueError('Truncated DSP ADPCM samples')
    out = np.empty(count, dtype='<i2')
    previous = older = 0
    for i in range(count):
        frame, sample = divmod(i, 14)
        head = data[frame*8]
        predictor = head>>4
        if predictor>7:
            raise ValueError('DSP predictor exceeds its coefficient table')
        value = data[frame*8+1+sample//2]
        value = (value&15) if sample%2 else value>>4
        if value>=8:value-=16
        a, b = coefficients[predictor*2:predictor*2+2]
        decoded = ((value*(1<<(head&15)))*2048+int(a)*previous+int(b)*older+1024)>>11
        decoded = max(-32768, min(32767, decoded))
        out[i]=decoded;older,previous=previous,decoded
    return out


def metadata(data: bytes) -> dict:
    if len(data)<64 or data[:6]!=b'CWAV\xff\xfe':
        raise ValueError('Expected little-endian Nintendo 3DS CWAV')
    u32=lambda p:struct.unpack_from('<I',data,p)[0]
    size=u32(12)
    if size!=len(data):raise ValueError('CWAV size does not match its container')
    info, audio=u32(24),u32(36)
    if info+36>size or audio+8>size or data[info:info+4]!=b'INFO' or data[audio:audio+4]!=b'DATA':
        raise ValueError('CWAV INFO/DATA bounds are invalid')
    rate,start,count,channels=u32(info+12),u32(info+16),u32(info+20),u32(info+28)
    if not 4000<=rate<=192000 or not 1<=channels<=8 or not 0<count<=rate*60 or start>=count:
        raise ValueError('CWAV sample/channel/loop bounds are invalid')
    return dict(codec=data[info+8],loop=bool(data[info+9]),rate=rate,start=start,
                samples=count,channels=channels,info=info,audio=audio)


def decode(data: bytes) -> tuple[np.ndarray, dict]:
    meta=metadata(data);table=meta['info']+28
    u32=lambda p:struct.unpack_from('<I',data,p)[0]
    result=[]
    for channel in range(meta['channels']):
        entry=table+u32(table+8+channel*8)
        if entry+16>len(data):raise ValueError('CWAV channel reference is outside the file')
        begin=meta['audio']+8+u32(entry+4)
        codec=meta['codec'];count=meta['samples']
        if codec==2:
            coefs=entry+u32(entry+12)
            coefficients=struct.unpack_from('<16h',data,coefs)
            result.append(dsp_pcm(data[begin:],coefficients,count))
        elif codec==1:
            if begin+count*2>len(data):raise ValueError('Truncated CWAV PCM16')
            result.append(np.frombuffer(data,dtype='<i2',count=count,offset=begin))
        elif codec==0:
            if begin+count>len(data):raise ValueError('Truncated CWAV PCM8')
            result.append(np.frombuffer(data,dtype='i1',count=count,offset=begin).astype('<i2')*256)
        else:raise ValueError(f'Unsupported CWAV codec {codec}')
    return np.column_stack(result),meta
