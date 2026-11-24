"""Bind animated eyelid images and source UV transforms before atlas baking."""
from pathlib import Path
import bpy
from .source_materials import uv_parameter


def repair_uvs(material,source,animated,raw,uv_name):
    tree=material.node_tree;group=tree.nodes['Group'];images={};parameters={}
    for n in tree.nodes:
        if n.type=='TEX_IMAGE' and n.image:images[Path(n.image.filepath).name]=n
    opacity=source.get('colors',{}).get('BaseColor',[1,1,1,1])[3]
    if opacity<1 and any(s.startswith('Transparent') for s in source.get('shaders',{})):
        alpha=group.inputs['AlbedoAlpha'];node=tree.nodes.new('ShaderNodeMath');node.operation='MULTIPLY'
        if alpha.is_linked:tree.links.new(alpha.links[0].from_socket,node.inputs[0])
        else:node.inputs[0].default_value=alpha.default_value
        node.inputs[1].default_value=opacity;tree.links.new(node.outputs[0],alpha)
        material['sourceOpacityBaked']=opacity
    for parameter,file in source['textures'].items():
        if parameter!='LayerMaskMap':continue
        relative=Path(file).with_suffix('.png');node=images.get(relative.name)
        if node is None:
            node=tree.nodes.new('ShaderNodeTexImage');node.image=bpy.data.images.load(str(Path(raw)/relative),check_existing=True)
            images[relative.name]=node
        node.image.alpha_mode='CHANNEL_PACKED';node.image.colorspace_settings.name='Non-Color'
        tree.links.new(node.outputs['Color'],group.inputs['Lym_color'])
        tree.links.new(node.outputs['Alpha'],group.inputs['Lym_alpha'])
    # Unlit LED eyes may have a secondary, constant-black iris mask. The pinned
    # importer lets OpacityMap1 overwrite the primary eye-expression atlas.
    if 'Unlit' in source['shaders'] and 'OpacityMap' in source['textures']:
        relative=Path(source['textures']['OpacityMap']).with_suffix('.png');path=Path(raw)/relative
        if not path.exists():raise FileNotFoundError(path)
        node=images.get(relative.name)
        if node is None:
            node=tree.nodes.new('ShaderNodeTexImage');node.image=bpy.data.images.load(str(path),check_existing=True);images[relative.name]=node
        node.image.colorspace_settings.name='Non-Color'
        tree.links.new(node.outputs['Color'],group.inputs['Mask'])
    # The pinned importer omitted upper eyelids and ignores UVScaleOffset4.
    for param,color,alpha in [('UpperEyelidColorMap','UpEye_alb','UpEye_alpha'),('LowerEyelidColorMap','LowEye_alb','LowEye_alpha')]:
        if param not in source['textures']:continue
        relative=Path(source['textures'][param]).with_suffix('.png');name=relative.name;path=Path(raw)/relative
        if not path.exists():raise FileNotFoundError(path)
        # Upper/lower controllers can share an image but have distinct UVs.
        node=tree.nodes.new('ShaderNodeTexImage');node.image=bpy.data.images.load(str(path),check_existing=True)
        parameters[param]=node
        # Blinks slide half-sheet masks beyond the eye UV rectangle. Repeating
        # them wraps the opposite lid back over an open eye.
        node.extension='CLIP'
        tree.links.new(node.outputs['Color'],group.inputs[color]);tree.links.new(node.outputs['Alpha'],group.inputs[alpha])
    for param,file in source['textures'].items():
        name=Path(file).stem+'.png';node=parameters.get(param,images.get(name))
        if node is None:continue
        key=uv_parameter(param)
        if key not in animated and 'Eyelid' not in param:continue
        transform=animated.get(key,source['colors'].get(key,[1,1,0,0]))
        # Keep a source UV2 mapping where explicitly authored by the importer.
        linked=node.inputs['Vector'].links
        original=linked[0].from_node if linked else None
        index='UV2Map' if original and original.type=='UVMAP' and original.uv_map=='UV2Map' else uv_name
        uv=tree.nodes.new('ShaderNodeUVMap');uv.uv_map=index
        mapping=tree.nodes.new('ShaderNodeMapping');mapping.vector_type='POINT'
        mapping.inputs['Scale'].default_value=(transform[0],transform[1],1)
        # Source UV coordinates use top-left V; Blender uses bottom-left V.
        mapping.inputs['Location'].default_value=(transform[2],1-transform[1]-transform[3],0)
        vector=uv.outputs['UV']
        if 'Eyelid' in param:
            # Source face charts can be on tile 2/3 (Tadbulb is on tile 2).
            # Repeat the source chart before sliding the non-repeating lid;
            # clamping the unwrapped chart would paint its opaque border over
            # the entire open eye.
            repeat=tree.nodes.new('ShaderNodeVectorMath');repeat.operation='FRACTION'
            tree.links.new(vector,repeat.inputs[0]);vector=repeat.outputs[0]
        tree.links.new(vector,mapping.inputs['Vector']);vector=mapping.outputs['Vector']
        if 'Eyelid' in param:
            # Source lid samplers repeat horizontally even when the animated
            # vertical slide must become transparent outside the sheet. A
            # whole U tile offset (Wo-Chien/Wattrel) must not erase the lid.
            split=tree.nodes.new('ShaderNodeSeparateXYZ');tree.links.new(vector,split.inputs['Vector'])
            repeat=tree.nodes.new('ShaderNodeMath');repeat.operation='FRACT';tree.links.new(split.outputs['X'],repeat.inputs[0])
            combine=tree.nodes.new('ShaderNodeCombineXYZ');tree.links.new(repeat.outputs[0],combine.inputs['X']);tree.links.new(split.outputs['Y'],combine.inputs['Y'])
            vector=combine.outputs['Vector']
        tree.links.new(vector,node.inputs['Vector'])
