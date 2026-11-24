"""Expose the pinned diffuse RGB and restore authored layered emission colors."""
import bpy


def portable_unlit(material,source):
    tree=material.node_tree;group=tree.nodes['Group']
    color=expose_diffuse(group)
    if 'BaseColorMap' not in source['textures']:
        node=tree.nodes.new('ShaderNodeRGB')
        node.outputs[0].default_value=source['colors'].get('BaseColor',(1,1,1,1));color=node.outputs[0]
    shader=tree.nodes.new('ShaderNodeBsdfDiffuse');tree.links.new(color,shader.inputs['Color'])
    opacity=group.inputs['Mask']
    return shader.outputs[0],opacity.links[0].from_socket if 'OpacityMap' in source['textures'] and opacity.is_linked else None


def expose_diffuse(group):
    graph=group.node_tree
    if 'PortableDiffuse' in group.outputs:return group.outputs['PortableDiffuse']
    outer=next(n for n in graph.nodes if n.type=='GROUP_OUTPUT')
    link=outer.inputs['BaseColorBake'].links[0]
    inner=link.from_node;index=list(inner.outputs).index(link.from_socket)
    inner_output=next(n for n in inner.node_tree.nodes if n.type=='GROUP_OUTPUT')
    shader=inner_output.inputs[index].links[0].from_node
    inner.node_tree.interface.new_socket(name='PortableDiffuse',in_out='OUTPUT',socket_type='NodeSocketColor')
    inner.node_tree.links.new(shader.inputs['Base Color'].links[0].from_socket,inner_output.inputs['PortableDiffuse'])
    graph.interface.new_socket(name='PortableDiffuse',in_out='OUTPUT',socket_type='NodeSocketColor')
    graph.links.new(inner.outputs['PortableDiffuse'],outer.inputs['PortableDiffuse'])
    return group.outputs['PortableDiffuse']


def eyelid_color(material,color):
    tree=material.node_tree;group=tree.nodes['Group']
    for prefix in ('UpEye','LowEye'):
        alpha=group.inputs[prefix+'_alpha'];albedo=group.inputs[prefix+'_alb']
        if not alpha.is_linked or not albedo.is_linked:continue
        node=tree.nodes.new('ShaderNodeMixRGB');node.blend_type='MIX'
        tree.links.new(alpha.links[0].from_socket,node.inputs[0])
        tree.links.new(color,node.inputs[1]);tree.links.new(albedo.links[0].from_socket,node.inputs[2]);color=node.outputs[0]
    return color


def portable_diffuse(material):
    tree=material.node_tree;shader=tree.nodes.new('ShaderNodeBsdfDiffuse')
    tree.links.new(eyelid_color(material,expose_diffuse(tree.nodes['Group'])),shader.inputs['Color'])
    return shader.outputs[0]


def portable_emission(material):
    tree=material.node_tree;group=tree.nodes['Group'];base=expose_diffuse(group)
    def rgb(value):
        n=tree.nodes.new('ShaderNodeRGB');n.outputs[0].default_value=value;return n.outputs[0]
    def socket(name,default):
        s=group.inputs.get(name)
        if s and s.is_linked:return s.links[0].from_socket
        v=s.default_value if s else default
        return rgb(v if hasattr(v,'__len__') else (v,v,v,1))
    def mix(kind,a,b,factor=1):
        n=tree.nodes.new('ShaderNodeMixRGB');n.blend_type=kind
        n.inputs[0].default_value=factor
        tree.links.new(a,n.inputs[1]);tree.links.new(b,n.inputs[2]);return n
    # Portable albedo has no HDR emission channel. Composite authored emitting
    # layers over their diffuse color instead of adding and clipping each RGB
    # channel to white (especially visible on green/pink eye layers).
    coverage=rgb((1,1,1,1))
    for name in ('UpEye_alpha','LowEye_alpha'):
        lid=group.inputs.get(name)
        if not lid or not lid.is_linked:continue
        inverse=tree.nodes.new('ShaderNodeMath');inverse.operation='SUBTRACT';inverse.use_clamp=True
        inverse.inputs[0].default_value=1;tree.links.new(lid.links[0].from_socket,inverse.inputs[1])
        coverage=mix('MULTIPLY',coverage,inverse.outputs[0]).outputs[0]
    def overlay(color,amount):
        nonlocal base
        factor=tree.nodes.new('ShaderNodeMath');factor.operation='MULTIPLY';factor.use_clamp=True
        tree.links.new(amount,factor.inputs[0]);tree.links.new(coverage,factor.inputs[1])
        node=mix('MIX',base,color);tree.links.new(factor.outputs[0],node.inputs[0]);base=node.outputs[0]
    # A separate emission map contributes light only where its pixels emit.
    # Blending black map pixels over diffuse would darken the entire body.
    emitted=mix('MULTIPLY',socket('Emission',(0,0,0,1)),socket('EmissionStrength',0)).outputs[0]
    emitted=mix('MULTIPLY',emitted,coverage).outputs[0]
    base=mix('ADD',base,emitted).outputs[0]
    lym=socket('Lym_color',(0,0,0,1));alpha=socket('Lym_alpha',0)
    separate=tree.nodes.new('ShaderNodeSeparateColor');tree.links.new(lym,separate.inputs[0])
    for i in range(1,5):
        mask=separate.outputs[i-1] if i<4 else alpha
        intensity=group.inputs['EmissionIntensityLayer'+str(i)].default_value
        factor=tree.nodes.new('ShaderNodeMath');factor.operation='MULTIPLY';factor.use_clamp=True
        tree.links.new(mask,factor.inputs[0]);factor.inputs[1].default_value=2*intensity
        overlay(socket('EmissionColorLayer'+str(i),(0,0,0,1)),factor.outputs[0])
    shader=tree.nodes.new('ShaderNodeBsdfDiffuse');tree.links.new(eyelid_color(material,base),shader.inputs['Color'])
    return shader.outputs[0]
