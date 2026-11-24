"""Read-only ORAS Cosplay Pikachu extraction through the local 3DS writer.

BCH/GF1 decoding uses the pinned SPICA checkout already used by this island.
The supplied ROM is never opened writable. All source GARC slots are retained.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess

from .cgfx_tool import ensure_cgfx_bridge,SPICA_COMMIT
from .container import ThreedsImage,parse_garc
from .lz11 import maybe_decompress
from .rom import parse_model_header_table,parse_generic_pack_offsets
from .oras_portable import write_portable

FORMS={2:'Pikachu_Rock_Star',3:'Pikachu_Belle',4:'Pikachu_Pop_Star',
       5:'Pikachu_PhD',6:'Pikachu_Libre',7:'Pikachu_Cosplay'}
GARC='/a/0/0/8'


def package_entries(blob):
    offsets=parse_generic_pack_offsets(blob)
    if not offsets or offsets[-1][1]>len(blob):raise ValueError('Invalid ORAS package bounds')
    return [blob[start:end] for start,end in offsets]


def ensure_bridge():
    existing=ensure_cgfx_bridge()
    root=existing.parent.parent
    revision=subprocess.check_output(['git','-C',str(root/'spica'),'rev-parse','HEAD'],text=True).strip()
    if revision!=SPICA_COMMIT:raise ValueError('The ORAS bridge requires the pinned SPICA revision')
    source=Path(__file__).with_name('bch_bridge')/'Program.cs'
    project=root/'oras_bridge';project.mkdir(exist_ok=True)
    csproj=project/'Rae.OrasBridge.csproj'
    csproj.write_text('<Project Sdk="Microsoft.NET.Sdk"><PropertyGroup><OutputType>Exe</OutputType>'
        '<TargetFramework>net8.0</TargetFramework><RollForward>Major</RollForward>'
        '<ImplicitUsings>enable</ImplicitUsings><Nullable>enable</Nullable></PropertyGroup><ItemGroup>'
        '<ProjectReference Include="../spica/SPICA/SPICA.csproj" /></ItemGroup></Project>')
    shutil.copyfile(source,project/'Program.cs')
    output=root/'oras-bin'
    built=subprocess.run(['dotnet','build',str(csproj),'-c','Release','-o',str(output),'--nologo'],
                   stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True)
    if built.returncode:raise RuntimeError('ORAS bridge build failed:\n'+built.stdout)
    return output/'Rae.OrasBridge.dll'


def extract(rom: Path,output: Path,forms=None):
    output=output.resolve();output.mkdir(parents=True,exist_ok=True)
    bridge=ensure_bridge();manifest_path=output/'manifest.json'
    previous=json.loads(manifest_path.read_text()) if manifest_path.exists() else {}
    if previous and previous.get('sourceRom')!=rom.name:raise ValueError('Output belongs to a different source ROM')
    results={e['formNumber']:e for e in previous.get('models',[])}
    with ThreedsImage(rom) as image:
        code=image.main_partition().product_code
        if not code.split('-')[-1].startswith(('ECR','ECL')):raise ValueError('Expected an ORAS cartridge product code')
        entry=next(f for f in image.romfs_files() if f.path==GARC)
        slots=parse_garc(image,entry.offset)
        table=parse_model_header_table(image.read(slots[0].offset,slots[0].size))
        group,count,flags=table[24]
        if count!=8 or flags!=7:raise ValueError('Unexpected Pikachu form table; refusing guessed slot identities')
        for form in forms or FORMS:
            label=FORMS[form];directory=output/label;raw=directory/'raw';raw.mkdir(parents=True,exist_ok=True)
            old=results.get(form)
            if old and Path(old['path']).exists() and hashlib.sha256(Path(old['path']).read_bytes()).hexdigest()!=old['sha256']:
                raise ValueError('Refusing to overwrite a modified source export: '+old['path'])
            base=3+(group+form)*8;payloads=[];manifest=[]
            for offset in range(8):
                slot=slots[base+offset];source=image.read(slot.offset,slot.size);decoded=maybe_decompress(source)
                (raw/f'slot{offset}.source').write_bytes(source);(raw/f'slot{offset}.bin').write_bytes(decoded)
                payloads.append(decoded);manifest.append({'slot':base+offset,'offset':offset,
                    'sourceSha256':hashlib.sha256(source).hexdigest(),'decodedSha256':hashlib.sha256(decoded).hexdigest()})
            job={'output':str(directory/'decoded')}
            for name,offset in [('model',0),('normal',2),('rare',3),('battle',5),('care',6)]:
                payload=package_entries(payloads[offset])[0]
                if name in ('battle','care') and not 1<=int.from_bytes(payload[:4],'little')<=0x10000:
                    # The uncostumed Cosplay body stores animation references.
                    # Its common Pikachu rig uses the base form's GF1 bank.
                    parent_slot=slots[3+(group+1)*8+offset]
                    parent=maybe_decompress(image.read(parent_slot.offset,parent_slot.size))
                    (raw/f'shared_{name}_form01.bin').write_bytes(parent)
                    payload=package_entries(parent)[0]
                    manifest.append({'animation':name,'sharedSourceForm':1,'slot':parent_slot.index,
                        'file':f'shared_{name}_form01.bin',
                        'decodedSha256':hashlib.sha256(parent).hexdigest()})
                path=raw/(name+'.bin');path.write_bytes(payload);job[name]=str(path)
            (directory/'job.json').write_text(json.dumps(job,indent=2)+'\n')
            with (directory/'decode.log').open('w') as log:
                subprocess.run(['dotnet',str(bridge),str(directory/'job.json')],check=True,stdout=log,stderr=subprocess.STDOUT)
            path=write_portable(directory/'decoded/decoded.json',directory/f'pm0025_{form:02}_{label}.glb')
            result={'species':25,'label':label,'formNumber':form,'sourceAssetId':f'oras_pikachu_{form:02}',
                'sourceRom':rom.name,'sourceGarc':GARC,'productCode':code,'files':manifest,
                'path':str(path),'sha256':hashlib.sha256(path.read_bytes()).hexdigest()}
            (directory/'source_manifest.json').write_text(json.dumps(result,indent=2)+'\n');results[form]=result
            print(label,'exported',flush=True)
    manifest_path.write_text(json.dumps({'sourceRom':rom.name,'models':[results[k] for k in sorted(results)]},indent=2)+'\n')


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('rom',type=Path);parser.add_argument('output',type=Path)
    parser.add_argument('--forms',type=int,nargs='+',choices=FORMS)
    args=parser.parse_args();extract(args.rom.resolve(),args.output,args.forms)
