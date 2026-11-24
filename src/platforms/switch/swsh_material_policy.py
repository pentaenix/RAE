"""Keep inactive zero-light Sword emission envelopes from occluding the body."""
import re
from pathlib import Path
import sys

from PIL import Image

from .gltf.glb_io import read_glb


def zero_light_envelope(values,flags,extrema):
    return (values.get('BlendMode')==5 and values.get('PreMultiplieMode')==1
        and not flags.get('DepthWrite',True) and extrema[:3]==((0,0),(0,0),(0,0)))


def apply_source_composite_policy(path,job):
    deps=Path(job['dependencies'])
    for directory in (deps/'python',deps/'pokemon_switch'):
        if str(directory) not in sys.path:sys.path.insert(0,str(directory))
    from GFLib.Model.Model import Model
    raw=Path(job['raw']);source=Model.GetRootAsModel((raw/job['modelFile']).read_bytes(),0)
    names=set()
    for i in range(source.MaterialsLength()):
        material=source.Materials(i);common=material.Common()
        values={common.Values(j).Name().decode():common.Values(j).Value() for j in range(common.ValuesLength())}
        flags={common.Switches(j).Name().decode():common.Switches(j).Value() for j in range(common.SwitchesLength())}
        for j in range(material.TextureMapsLength()):
            texture=material.TextureMaps(j)
            if texture.Sampler()!=b'Col0Tex':continue
            image=raw/(source.TextureNames(texture.Index()).decode()+'.png')
            if image.exists():
                with Image.open(image) as pixels:
                    if zero_light_envelope(values,flags,pixels.getextrema()):names.add(material.Name().decode())
    if not names:return []
    glb=read_glb(path);changed=[]
    for material in glb.json['materials']:
        name=re.split(r'\.\d{3}(?:_|$)',material.get('name',''),maxsplit=1)[0].removesuffix('_shiny')
        if name not in names:continue
        extra=material.setdefault('extras',{}).setdefault('rae',{})
        # This source pass contributes zero light until its game effect runs.
        # Additive black is neutral; ordinary alpha black hides the real horn.
        extra.update(renderClass='additive',sourceCompositeFallback='zero-light-emission-envelope',sourcePremultiplyMode=1)
        material['alphaMode']='BLEND';changed.append(material['name'])
    if changed:glb.write(path)
    return changed
