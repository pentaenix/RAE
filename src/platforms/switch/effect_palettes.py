"""Read original normal/shiny surface-effect color uniforms from Sword models."""
import argparse
import hashlib
import json
from pathlib import Path
import sys

from .patch_romfs import PatchedSwitchRom
from .gfpak import read_gfpak
from .fnv import fnv1a64


def export(base,update,output,species):
    deps=Path(__file__).resolve().parents[3]/'.cache/switch-tools'
    sys.path[:0]=[str(deps/'python'),str(deps/'pokemon_switch')]
    from GFLib.Model.Model import Model
    rows=[]
    with PatchedSwitchRom(base,update) as rom:
        files={Path(f.path).stem:f for f in rom.romfs_files() if '/archive/pokemon/' in f.path}
        for dex in species:
            entry=files.get(f'pm{dex:04d}_00_00') or files.get(f'pm{dex:04d}_00')
            if not entry:continue
            asset=Path(entry.path).stem;pack=rom.read_file(entry);bundle=read_gfpak(pack)
            row={'dex':dex,'sourcePack':entry.path,'packSha256':hashlib.sha256(pack).hexdigest(),'colors':{}}
            for rare in (False,True):
                filename=asset+('_rare' if rare else '')+'.gfbmdl'
                file=next((x for x in bundle if x.name_hash==fnv1a64(filename)),None)
                if file is None:continue
                model=Model.GetRootAsModel(file.data,0);materials=[]
                for i in range(model.MaterialsLength()):
                    mat=model.Materials(i);name=mat.Name().decode()
                    if not any(s in name.lower() for s in ('fire','flame','smoke')):continue
                    colors={mat.Colors(j).Name().decode():[getattr(mat.Colors(j).Color(),c)() for c in ('R','G','B')]
                            for j in range(mat.ColorsLength())}
                    values={mat.Values(j).Name().decode():mat.Values(j).Value() for j in range(mat.ValuesLength())}
                    materials.append({'name':name,'colors':colors,'colorLerpValue':values.get('ColorLerpValue'),
                                      'sourceModelSha256':hashlib.sha256(file.data).hexdigest()})
                row['colors']['shiny' if rare else 'normal']=materials
            rows.append(row)
    output.parent.mkdir(parents=True,exist_ok=True)
    output.write_text(json.dumps({'sourceRom':base.name,'sourceUpdate':update.name,'models':rows},indent=2)+'\n')
    print('Original effect palettes:',len(rows),'species')


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('rom',type=Path);p.add_argument('update',type=Path)
    p.add_argument('output',type=Path);p.add_argument('--species',type=int,nargs='+',required=True)
    a=p.parse_args();export(a.rom.resolve(),a.update.resolve(),a.output.resolve(),a.species)
