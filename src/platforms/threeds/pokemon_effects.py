"""Pokemon surface passes from original GFL2 shaders, separate from world policy."""
import struct

from .gf import is_gf_shader,parse_gf_shader


def shader_entries(package):
    """Bounded PC/PS packages; PS contains the Pokemon's visible shader bank."""
    if len(package)<8 or package[:2] not in (b'PC',b'PS'):return []
    count=struct.unpack_from('<H',package,2)[0];header=8+count*4
    if count>4096 or len(package)<header:raise ValueError('Invalid Pokemon shader package header')
    offsets=struct.unpack_from('<%dI'%(count+1),package,4)
    if offsets[0]<header or offsets[-1]>len(package) or any(a>b for a,b in zip(offsets,offsets[1:])):
        raise ValueError('Invalid Pokemon shader package bounds')
    return [package[a:b] for a,b in zip(offsets,offsets[1:])]


def attach_shaders(model,package):
    shaders={}
    for part in shader_entries(package):
        for payload in ([part] if is_gf_shader(part) else shader_entries(part)):
            if is_gf_shader(payload):
                shader=parse_gf_shader(payload);shaders[shader.name]=shader
    for material in model.materials:
        shader=shaders.get(material.fragment_shader_name)
        if shader:
            material.tev_stages=shader.stages;material.tev_buffer_color=shader.buffer_color
    return prepare_portable_surfaces(model)


def prepare_portable_surfaces(model):
    """Use the authored volume/coverage mesh instead of the framebuffer compositor.

    FireSten wraps the offscreen volume in a much larger compositing envelope.
    Its color constants belong on the core coverage in a standalone GLB.
    Original samplers and their UV motion remain attached to that coverage mesh.
    """
    stencils={m.name:m for m in model.materials if m.fragment_shader_name.casefold().startswith('firesten')}
    geoms={m.name:m for m in model.materials if m.fragment_shader_name.casefold().startswith('firegeom')}
    cores=[m for m in model.materials if m.fragment_shader_name.casefold().startswith('firecore')]
    for material in [*stencils.values(),*geoms.values(),*cores]:
        material.portable_effect_recipe='compositor' if material.name in stencils else 'distortion'
    for core in cores:
        stencil=stencils.get(core.name.replace('Core','Sten',1)) or next(iter(stencils.values()),None)
        if stencil is None:continue
        target=core
        target.portable_effect_recipe='smoke_core' if 'dogars' in stencil.fragment_shader_name.casefold() else 'core'
        colors=list(core.constant_colors)
        if len(colors)<6:continue
        colors[3:5]=stencil.constant_colors[3:5];colors[5]=(255,255,255,0)
        target.constant_colors=tuple(colors)
        target.constant_assignments=(3,4,5,4,0,0)
        target.tev_stages=portable_stages(target.portable_effect_recipe)
    return model


def portable_stages(recipe):
    """Original scrolling coverage controls heat; the core mesh bounds the flame.

    Fire coverage textures encode empty space as white. These were framebuffer
    inputs, not ordinary albedo/opacity maps. Smoke uses inverse coverage with
    the source opacity; flame retains the authored volume with two heat colors.
    """
    stages=[{'source':0x0333000e,'operand':0x2000,'combiner':0,'scale':0},
            {'source':0x0043000e,'operand':0x22000,'combiner':0x20000,'scale':0,'updateColorBuffer':True},
            {'source':0x0ffe03df,'operand':0x1500,'combiner':4,'scale':0}]
    passthrough={'source':0x0fff0fff,'operand':0,'combiner':0,'scale':0}
    stages.extend(dict(passthrough) for _ in range(3))
    if recipe=='smoke_core':
        stages[2]['source']=0x0fff03df
        stages[3].update(source=0x00ef000f,combiner=0x10000)
    return tuple(stages)


def effect_pass(material):
    if material.portable_effect_recipe in ('core','smoke_core'):return 'flame_or_smoke'
    if material.portable_effect_recipe in ('compositor','distortion'):return 'intermediate'
    shader=material.fragment_shader_name.casefold()
    if shader.startswith(('firecore','firegeom')):return 'intermediate'
    if shader.startswith('firesten'):return 'flame_or_smoke'
    if 'betbeton_beto' in shader:return 'wet_surface'
    return None


def surface_effect(material):
    return effect_pass(material) in ('flame_or_smoke','wet_surface') and bool(material.tev_stages)


def effect_motion(animations,model,names):
    from .motion import build_world_map_material_motion
    motion=build_world_map_material_motion(animations,model,material_names=names)
    if motion:
        motion['clips']=[clip for clip in motion['clips'] if clip.get('tracks')]
        if not motion['clips']:return None
        default=next((clip for clip in motion['clips'] if clip.get('loop')),motion['clips'][0])
        motion['defaultClip']=default['id'];motion.pop('overlayClips',None)
        for clip in motion['clips']:
            clip['loop']=True
            for key in ('meshVisibility','meshVisibilitySources','visibilityMaterials'):clip.pop(key,None)
    return motion


def portable_colors(material,colors):
    """Packed PDC/PTS vertex RGB can be a specular mask, not albedo tint."""
    if not material or not material.fragment_shader_name.startswith(('PDC_','PTS_')) or not material.tev_stages:
        return colors
    arity=(1,2,2,2,3,2,2,2,3,3)
    for stage in material.tev_stages:
        mode=int(stage['combiner'])&15
        for arg in range(arity[mode] if mode<len(arity) else 3):
            source=(int(stage['source'])>>(arg*4))&15
            operand=(int(stage['operand'])>>(arg*4))&15
            if source==0 and operand not in (2,3):return colors
    return [(1.,1.,1.,c[3]) for c in colors]
