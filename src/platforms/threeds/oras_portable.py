"""Adapt the isolated BCH bridge's decoded data to the native 3DS GLB writer."""
from dataclasses import dataclass
import json
from pathlib import Path

from PIL import Image

from .gf import GfBone,GfMaterial,GfMesh,GfModel,GfSubMesh,GfTextureUnit
from .glb import write_model_glb
from .motion import GfMotion,GfMotBoneTrack,GfMotKey
from .pica import rgba_to_png
from .pica_material import PicaRenderState
from .gltf.glb_io import read_glb


@dataclass
class DecodedTexture:
    name: str
    width: int
    height: int
    rgba: bytes

    def decode_rgba(self):return self.rgba
    def to_png(self):return rgba_to_png(self.rgba,self.width,self.height)


def canonical_skin(submesh):
    """Merge palette aliases without changing the weighted deformation."""
    for row,(joints,weights) in enumerate(zip(submesh.joints,submesh.weights)):
        merged={}
        for joint,weight in zip(joints,weights):
            if weight>0:merged[joint]=merged.get(joint,0)+weight
        if not merged:merged={0:1}
        total=sum(merged.values());items=list(merged.items())
        submesh.joints[row]=tuple([j for j,_ in items]+[0]*(4-len(items)))
        submesh.weights[row]=tuple([w/total for _,w in items]+[0.]*(4-len(items)))
    return submesh


def material_from_bridge(source):
    material=dict(source)
    material['render_state']=PicaRenderState(**material['render_state'])
    material['texture_names']=[n for n in material['texture_names'] if n]
    material['texture_units']=[GfTextureUnit(**unit) for unit in material['texture_units'] if unit['name']]
    return GfMaterial(**material)


def write_portable(decoded: Path,output: Path):
    data=json.loads(decoded.read_text())
    model=GfModel(data['name'])
    model.bones=[GfBone(**b) for b in data['bones']]
    model.materials=[material_from_bridge(material) for material in data['materials']]
    model.material_names=[m.name for m in model.materials]
    model.texture_names=sorted({n for m in model.materials for n in m.texture_names})
    for mesh in data['meshes']:
        model.meshes.append(GfMesh(mesh['name'],[canonical_skin(GfSubMesh(**s)) for s in mesh['submeshes']]))
    def textures(color):
        result=[]
        for item in data[color]:
            with Image.open(item['path']) as image:
                result.append(DecodedTexture(item['name'],item['width'],item['height'],image.convert('RGBA').tobytes()))
        return result
    motions=[]
    for clip in data['animations']:
        tracks=[GfMotBoneTrack(track['name'],False,
                    [[GfMotKey(i,value,0) for i,value in enumerate(channel)] for channel in track['channels']])
                for track in clip['bones']]
        motions.append(GfMotion(clip['name'],clip['frames'],False,tracks))
    path=write_model_glb(model,textures('normal'),output,animations=motions,shiny_textures=textures('rare'))
    glb=read_glb(path);rae=glb.json.setdefault('extras',{}).setdefault('rae',{})
    rae.update(sourceGame='omega-ruby-alpha-sapphire',sourceFormat='BCH/GF1',sourceClipCount=len(motions),
               sourceFrameRate=30,sourceClipNames=[m.name for m in motions],
               rawOnly=['ORAS material-motion packages and shader data remain in raw/'])
    glb.write(path)
    return path
