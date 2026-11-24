"""Re-export selected Ultra Moon species with original surface shader data."""
import argparse
import hashlib
import json
from pathlib import Path

from .rom import read_garc_slot,parse_model_header_table,POKEMON_MODEL_GARC,MODEL_GROUP_STRIDE
from .service import build_model_glb,load_model,load_motions
from .species import species_name
from .pokemon_effects import portable_stages,surface_effect,effect_motion
from .gltf.glb_io import read_glb


def descriptor_for(table,rom,dex):
    group,_,_=table[dex-1]
    return {'type':'model','rom':str(rom),'garc':POKEMON_MODEL_GARC,'species':dex,
        'group':group,'base_slot':1+group*MODEL_GROUP_STRIDE,'form':0,'name':species_name(dex)}


def refresh_recipes(output,rom,refresh_motion=False):
    """Refresh derived TEV words without resampling unchanged skeletal clips."""
    manifest_path=output/'manifest.json';manifest=json.loads(manifest_path.read_text())
    if rom.name!=manifest['sourceRom']:raise ValueError('Source ROM differs from exported models')
    table=parse_model_header_table(read_garc_slot(rom,POKEMON_MODEL_GARC,0)) if refresh_motion else None
    for row in manifest['models']:
        path=output/row['file']
        if hashlib.sha256(path.read_bytes()).hexdigest()!=row['sha256']:raise ValueError('Stale GLB: '+path.name)
        glb=read_glb(path)
        for material in glb.json['materials']:
            extra=material.get('extras',{}).get('rae',{});recipe=extra.get('standaloneEffectRecipe')
            if recipe not in ('core','smoke_core'):continue
            extra['picaTev']['stages']=[dict(stage) for stage in portable_stages(recipe)]
            extra['picaTev']['constantAssignments']=[3,4,5,4,0,0]
            extra['picaTev']['constantColors'][5]=[1.,1.,1.,0.]
        if refresh_motion:
            descriptor=descriptor_for(table,rom,row['dex']);model=load_model(descriptor)
            names={m.name for m in model.materials if surface_effect(m)}
            motion=effect_motion(load_motions(descriptor),model,names)
            extra=glb.json.setdefault('extras',{}).setdefault('rae',{})
            if motion:extra['pokemonMaterialMotion']=motion
            else:extra.pop('pokemonMaterialMotion',None)
        glb.write(path);row['sha256']=hashlib.sha256(path.read_bytes()).hexdigest()
    manifest_path.write_text(json.dumps(manifest,indent=2)+'\n')


def export(rom,output,species):
    output.mkdir(parents=True,exist_ok=True)
    manifest=output/'manifest.json'
    previous=json.loads(manifest.read_text()) if manifest.exists() else {}
    if previous.get('sourceRom',rom.name)!=rom.name:raise ValueError('Source ROM differs from previous export')
    table=parse_model_header_table(read_garc_slot(rom,POKEMON_MODEL_GARC,0))
    rows={r['dex']:r for r in previous.get('models',[])}
    for dex in species:
        if not 1<=dex<=min(807,len(table)):raise ValueError('Expected an Ultra Moon species number')
        descriptor=descriptor_for(table,rom,dex)
        path=build_model_glb(descriptor,output)
        rows[dex]={'dex':dex,'file':path.name,'sha256':hashlib.sha256(path.read_bytes()).hexdigest()}
        print('Exported',path.name,flush=True)
    manifest.write_text(json.dumps({'sourceRom':rom.name,'models':[rows[dex] for dex in sorted(rows)]},indent=2)+'\n')


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('rom',type=Path);parser.add_argument('output',type=Path)
    parser.add_argument('--species',type=int,nargs='+',default=[6,77,78,88,89,109,110,392])
    parser.add_argument('--refresh-material-recipes',action='store_true')
    parser.add_argument('--refresh-material-motion',action='store_true')
    args=parser.parse_args()
    if args.refresh_material_recipes or args.refresh_material_motion:
        refresh_recipes(args.output.resolve(),args.rom.resolve(),args.refresh_material_motion)
    else:export(args.rom.resolve(),args.output.resolve(),args.species)
