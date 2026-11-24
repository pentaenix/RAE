"""Read authored SV shader state for offline portable-material repair."""
from pathlib import Path
import sys


def read_materials(job, shiny=False):
    deps=Path(job['dependencies']);sys.path[:0]=[str(deps/'python'),str(deps/'pokemon_switch')]
    from Titan.Model.TRMTR import TRMTR
    raw=Path(job['raw']);stem=Path(job['modelFile']).stem
    path=raw/(stem+('_rare' if shiny else '')+'.trmtr')
    if not path.exists():path=raw/(stem+'.trmtr')
    root=TRMTR.GetRootAs(path.read_bytes(),0);result={}
    for i in range(root.MaterialsLength()):
        m=root.Materials(i)
        floats={m.FloatParameter(j).FloatName().decode():m.FloatParameter(j).FloatValue() for j in range(m.FloatParameterLength())}
        colors={m.Float4Parameter(j).ColorName().decode():[getattr(m.Float4Parameter(j).ColorValue(),x)() for x in 'RGBA'] for j in range(m.Float4ParameterLength())}
        textures={m.Textures(j).TextureName().decode():m.Textures(j).TextureFile().decode() for j in range(m.TexturesLength())}
        shaders={m.Shaders(j).ShaderName().decode():{m.Shaders(j).ShaderValues(k).StringName().decode():m.Shaders(j).ShaderValues(k).StringValue().decode() for k in range(m.Shaders(j).ShaderValuesLength())} for j in range(m.ShadersLength())}
        result[m.Name().decode()]={'floats':floats,'colors':colors,'textures':textures,'shaders':shaders,'alpha':m.AlphaType().decode()}
    return result


def emits_black_layers(source):
    f,c=source['floats'],source['colors']
    return any(f.get('EmissionIntensityLayer'+str(i),0)>0 and
               max(c.get('BaseColorLayer'+str(i),[1,1,1])[:3])<.001 and
               max(c.get('EmissionColorLayer'+str(i),[0,0,0])[:3])>.01 for i in range(1,5))


def uv_parameter(texture):
    if texture.startswith('UpperEyelid'):return 'UVScaleOffset3'
    if texture.startswith('LowerEyelid'):return 'UVScaleOffset4'
    return 'UVScaleOffset1' if texture.endswith('1') else 'UVScaleOffset'


def has_emission(source):
    floats,colors=source['floats'],source['colors']
    if 'Unlit' in source.get('shaders',{}) and floats.get('EmissionIntensity',0)>0:return True
    if floats.get('EmissionIntensity',0)>0 and ('EmissionColorMap' in source.get('textures',{}) or max(colors.get('EmissionColor',[0,0,0])[:3])>0):return True
    return any(floats.get('EmissionIntensityLayer'+str(i),0)>0 and
               max(colors.get('EmissionColorLayer'+str(i),[0,0,0])[:3])>0 for i in range(1,5))


def portable_emission_required(source):
    return has_emission(source)
