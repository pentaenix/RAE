"""Read 3DS CSAR bank-to-wave references without synthesizing CSEQ tracks."""
from __future__ import annotations
from dataclasses import dataclass
import struct


@dataclass(frozen=True)
class ArchiveWave:
    bank: str
    archive_id: int
    wave_index: int
    offset: int
    data: bytes


class SoundArchive:
    def __init__(self, data: bytes):
        self.data=data
        if data[:6]!=b'CSAR\xff\xfe':raise ValueError('Expected little-endian 3DS CSAR')
        if self.u32(12)!=len(data):raise ValueError('CSAR file size mismatch')
        sections={data[self.u32(24+i*12):self.u32(24+i*12)+4]:self.u32(24+i*12)
                  for i in range(struct.unpack_from('<H',data,16)[0])}
        self.info=sections[b'INFO']+8
        self.files=sections[b'FILE']+8
        self.strings=sections[b'STRG']+8
        self.strings+=self.u32(self.strings+4)

    def u32(self, offset):
        if offset<0 or offset+4>len(self.data):raise ValueError('CSAR reference exceeds file bounds')
        return struct.unpack_from('<I',self.data,offset)[0]

    def record(self, kind, index):
        base=self.info+self.u32(self.info+kind*8+4)
        if index<0 or index>=self.u32(base):raise ValueError('CSAR table index exceeds its count')
        return base+self.u32(base+8+index*8)

    def string(self, index):
        if index>=self.u32(self.strings):raise ValueError('CSAR string index exceeds its count')
        entry=self.strings+4+index*12
        start=self.strings+self.u32(entry+4);length=self.u32(entry+8)
        if start+length>len(self.data):raise ValueError('CSAR string exceeds file bounds')
        return self.data[start:start+length].rstrip(b'\0').decode('utf-8')

    def file(self, index):
        entry=self.record(6,index)
        if self.u32(entry)!=0x220c:raise ValueError('Requested CSAR file is external')
        entry+=self.u32(entry+4)
        offset=self.files+self.u32(entry+4);size=self.u32(entry+8)
        if offset+size>len(self.data):raise ValueError('CSAR embedded file exceeds archive bounds')
        return offset,self.data[offset:offset+size]

    def bank_waves(self):
        base=self.info+self.u32(self.info+2*8+4)
        seen=set()
        for index in range(self.u32(base)):
            bank=self.record(2,index);name=self.string(self.u32(bank+16))
            _,raw=self.file(self.u32(bank))
            if raw[:4]!=b'CBNK':raise ValueError('CSAR bank does not reference CBNK')
            u=lambda p:struct.unpack_from('<I',raw,p)[0]
            info=u(24)+8;table=info+u(info+4)
            count=u(table)
            if count>4096:raise ValueError('CBNK wave count exceeds bounded export size')
            for i in range(count):
                archive_id,wave_index=struct.unpack_from('<II',raw,table+4+i*8)
                archive_id &= 0xffffff
                if (name,archive_id,wave_index) in seen:continue
                seen.add((name,archive_id,wave_index))
                arc=self.record(3,archive_id);offset,wave_archive=self.file(self.u32(arc))
                if wave_archive[:4]!=b'CWAR':raise ValueError('CSAR wave archive does not reference CWAR')
                a=lambda p:struct.unpack_from('<I',wave_archive,p)[0]
                info=a(24)+8
                if wave_index>=a(info):raise ValueError('CWAR wave index exceeds its count')
                entry=info+4+wave_index*12
                start=a(36)+8+a(entry+4);size=a(entry+8)
                if start+size>len(wave_archive):raise ValueError('CWAV exceeds its wave archive')
                yield ArchiveWave(name,archive_id,wave_index,offset+start,wave_archive[start:start+size])
