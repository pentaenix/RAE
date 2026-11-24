"""Portable authored sphere maps and linked flame masks for Sword materials.

Sphere highlights are baked in object space, a stable diffuse approximation of
the source view-dependent reflection. The raw shader/scroll tracks stay intact.
"""
from pathlib import Path
import bpy


def surface(tree,model,material,raw,maps,samplers,values,colors,flags,common,color,texture,uv,portable_masks=False):
    def image(key,vector=None):
        n=tree.nodes.new('ShaderNodeTexImage');name=model.TextureNames(maps[key]).decode()
        n.image=bpy.data.images.load(str(Path(raw)/(name+'.png')),check_existing=True)
        n.image.alpha_mode='CHANNEL_PACKED'
        if vector is not None:tree.links.new(vector,n.inputs['Vector'])
        return n
    def mix(a,b,factor=1,kind='MIX'):
        n=tree.nodes.new('ShaderNodeMixRGB');n.blend_type=kind;n.inputs[0].default_value=factor
        for x,s in ((a,1),(b,2)):
            if isinstance(x,tuple):n.inputs[s].default_value=x
            else:tree.links.new(x,n.inputs[s])
        return n.outputs[0]
    def rgb(name):
        c=colors[name];return (c.R(),c.G(),c.B(),1)
    def math(kind,a,b):
        n=tree.nodes.new('ShaderNodeMath');n.operation=kind
        for x,s in ((a,0),(b,1)):
            if isinstance(x,(int,float)):n.inputs[s].default_value=x
            else:tree.links.new(x,n.inputs[s])
        return n.outputs[0]
    alpha=None
    if portable_masks and material.Name().decode().startswith('FireMask'):
        link=values.get('MatLinkID');palette=None;amount=0
        for i in range(model.MaterialsLength()):
            m=model.Materials(i);v={m.Values(j).Name().decode():m.Values(j).Value() for j in range(m.ValuesLength())}
            if m.Name().decode().startswith('FireCore') and v.get('MatLinkID')==link:
                palette={m.Colors(j).Name().decode():m.Colors(j).Color() for j in range(m.ColorsLength())};amount=v.get('ColorLerpValue',0);break
        if palette:
            a,b=palette['BaseColor0'],palette['BaseColor1'];rgb_value=tuple(getattr(a,k)()*(1-amount)+getattr(b,k)()*amount for k in 'RGB')
            color_node=tree.nodes.new('ShaderNodeRGB');color_node.outputs[0].default_value=(*rgb_value,1);color=color_node.outputs[0]
        masks=[]
        for key in ('Mask0Texture','Mask1Texture'):
            if key not in maps:continue
            prefix=key[:5];n=image(key,uv(prefix,common.get('Color'+prefix+'UvIndex',0),None,samplers[key]));n.image.colorspace_settings.name='Non-Color';masks.append(n.outputs['Color'])
        if masks:
            masked=masks[0] if len(masks)==1 else math('MULTIPLY',*masks)
            # These are erase/stencil masks; black retains the flame shell.
            alpha=math('SUBTRACT',1,masked)
    if __package__:
        from .swsh_surface_policy import bake_sphere_reflection
    else:
        from swsh_surface_policy import bake_sphere_reflection
    if bake_sphere_reflection(material.Name().decode(),flags) and 'SphereMapTex' in maps:
        original_color=color
        normal=tree.nodes.new('ShaderNodeTexCoord');split=tree.nodes.new('ShaderNodeSeparateXYZ')
        tree.links.new(normal.outputs['Normal'],split.inputs[0]);combine=tree.nodes.new('ShaderNodeCombineXYZ')
        for source,dest in ((0,0),(2,1)):
            tree.links.new(math('MULTIPLY_ADD',split.outputs[source],.5),combine.inputs[dest])
            # MULTIPLY_ADD's third input is the disk's [0,1] center.
            combine.inputs[dest].links[0].from_node.inputs[2].default_value=.5
        env=image('SphereMapTex',combine.outputs[0])
        reflection=mix(env.outputs['Color'],rgb('SphereMapColor'),kind='MULTIPLY')
        color=mix(color,reflection,values.get('SphereMapColorVal',1),kind='ADD')
        # A diffuse-only renderer has no environment illumination. The source
        # shadow color supplies its authored minimum reflected metal/ice color.
        if 'ConstantColorSd0' in colors and not flags.get('SphereMaskEnable') and not flags.get('BaseColorAddEnable',True):
            color=mix(color,rgb('ConstantColorSd0'),kind='LIGHTEN')
        if flags.get('SphereMaskEnable') and 'AmbientTex' in maps:
            mask=image('AmbientTex',uv('Color',common.get('ColorMapUvIndex',0)))
            mask.image.colorspace_settings.name='Non-Color'
            split=tree.nodes.new('ShaderNodeSeparateColor');tree.links.new(mask.outputs['Color'],split.inputs[0])
            node=tree.nodes.new('ShaderNodeMixRGB');tree.links.new(split.outputs[1],node.inputs[0]);tree.links.new(original_color,node.inputs[1]);tree.links.new(color,node.inputs[2]);color=node.outputs[0]
    if not portable_masks and 'Blend0Tex' in maps and 'BaseColor0' in colors:
        flame=image('Blend0Tex',uv('Blend0',0))
        node=tree.nodes.new('ShaderNodeMixRGB');node.inputs[1].default_value=rgb('BaseColor0');node.inputs[2].default_value=rgb('LayerColor0')
        tree.links.new(flame.outputs['Color'],node.inputs[0]);color=node.outputs[0]
        link=values.get('MatLinkID')
        mask_material=None
        for i in range(model.MaterialsLength()):
            m=model.Materials(i);v={m.Values(j).Name().decode():m.Values(j).Value() for j in range(m.ValuesLength())}
            if m.Name().decode().startswith('FireMask') and v.get('MatLinkID')==link:mask_material=m;break
        if mask_material is not None:
            masks=[]
            for j in range(mask_material.TextureMapsLength()):
                t=mask_material.TextureMaps(j);key=t.Sampler().decode()
                if key not in ('Mask0Texture','Mask1Texture'):continue
                prefix=key[:5];cv=mask_material.Common();params={cv.Values(k).Name().decode():cv.Values(k).Value() for k in range(cv.ValuesLength())}
                mv={mask_material.Values(k).Name().decode():mask_material.Values(k).Value() for k in range(mask_material.ValuesLength())}
                n=tree.nodes.new('ShaderNodeTexImage');name=model.TextureNames(t.Index()).decode();n.image=bpy.data.images.load(str(Path(raw)/(name+'.png')),check_existing=True)
                n.image.colorspace_settings.name='Non-Color'
                tree.links.new(uv(prefix,params.get('Color'+prefix+'UvIndex',0),mv,t.Params()),n.inputs['Vector']);masks.append(n.outputs['Color'])
            if masks:alpha=masks[0] if len(masks)==1 else math('MULTIPLY',*masks)
    if common.get('BlendMode')==5 and texture is not None:
        alpha=texture.outputs.get('Alpha') if alpha is None else alpha
        if flags.get('Layer1Enable') and 'LyCol0Tex' in maps:
            layer=image('LyCol0Tex',uv('Layer1',common.get('Layer1UvIdx',0)))
            alpha=math('MULTIPLY',alpha,layer.outputs['Alpha'])
        alpha=math('MULTIPLY',alpha,values.get('ConstantAlpha',1)*values.get('OnGameAlpha',1))
    return color,alpha
