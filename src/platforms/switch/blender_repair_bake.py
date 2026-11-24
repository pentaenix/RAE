"""Selective portable atlas bake, retaining the exporter's full-mesh UV layout."""
from pathlib import Path
import bpy
import numpy as np
from .blender_materials import _bake_meshes


def bake_repaired_materials(output, targets, surfaces, packed_uvs=None, minimum_size=0):
    scene=bpy.context.scene;scene.render.engine='CYCLES';scene.cycles.device='CPU';scene.cycles.samples=1
    scene.render.bake.use_clear=False
    meshes=[o for o in scene.objects if o.type=='MESH'];images={};alpha={}
    for obj in meshes:
        bpy.ops.object.select_all(action='DESELECT');obj.select_set(True);bpy.context.view_layer.objects.active=obj
        source_uv=next(u.name for u in obj.data.uv_layers if u.active_render)
        for slot in obj.material_slots:
            source=slot.material;slot.material=source.copy();m=slot.material
            m['repair_source']=source.get('repair_source',source.name)
            m.name=f"{source.name}_{obj.name.removesuffix('_mesh')}"
            tree=m.node_tree;uv=tree.nodes.new('ShaderNodeUVMap');uv.uv_map=source_uv
            for n in list(tree.nodes):
                if n.type=='TEX_IMAGE' and not n.inputs['Vector'].is_linked:tree.links.new(uv.outputs['UV'],n.inputs['Vector'])
            target=m['repair_source'] in targets
            sizes=[max(n.image.size) for n in tree.nodes if n.type=='TEX_IMAGE' and n.image]
            size=max(minimum_size,min(1024,max(sizes,default=256))) if target else 4
            image=bpy.data.images.new(m.name+'_repair',size,size,alpha=True);image.generated_color=(0,0,0,1)
            image.alpha_mode='CHANNEL_PACKED'
            n=tree.nodes.new('ShaderNodeTexImage');n.image=image;tree.nodes.active=n
            surface,alpha_socket=surfaces(m) if target else (tree.nodes['Group'].outputs['BaseColorBake'],None)
            tree.links.new(surface,tree.nodes['Material Output'].inputs['Surface']);images[m]=image
            if target and alpha_socket is not None:alpha[m]=alpha_socket
        obj.data.uv_layers.new(name='RAE_Bake');obj.data.uv_layers.active_index=len(obj.data.uv_layers)-1
        bpy.ops.object.mode_set(mode='EDIT');bpy.ops.mesh.select_all(action='SELECT');bpy.ops.uv.smart_project(island_margin=.02);bpy.ops.object.mode_set(mode='OBJECT')
    if packed_uvs:
        from .blender_packed_uv import restore_mesh_uv
        for obj in meshes:restore_mesh_uv(obj,packed_uvs)
    selected=[o for o in meshes if any(s.material['repair_source'] in targets for s in o.material_slots)]
    _bake_meshes(selected)
    colors={m:np.array(images[m].pixels[:],dtype=np.float32).reshape((-1,4)) for m in alpha}
    for m,socket in alpha.items():
        tree=m.node_tree;shader=tree.nodes.new('ShaderNodeBsdfDiffuse')
        tree.links.new(socket,shader.inputs['Color']);tree.links.new(shader.outputs[0],tree.nodes['Material Output'].inputs['Surface'])
    if alpha:_bake_meshes([o for o in selected if any(s.material in alpha for s in o.material_slots)])
    for m,pixels in colors.items():
        pixels[:,3]=np.clip(np.array(images[m].pixels[:],dtype=np.float32).reshape((-1,4))[:,0],0,1)
        images[m].pixels.foreach_set(pixels.ravel());images[m].update()
    output=Path(output);output.mkdir(parents=True,exist_ok=True)
    for m,image in images.items():
        image.filepath_raw=str(output/(m.name+'.png'));image.file_format='PNG';image.save();image.pack()
        tree=m.node_tree;tree.nodes.clear();tex=tree.nodes.new('ShaderNodeTexImage');tex.image=image
        shader=tree.nodes.new('ShaderNodeBsdfPrincipled');tree.links.new(tex.outputs['Color'],shader.inputs['Base Color'])
        shader.inputs['Metallic'].default_value=0;shader.inputs['Roughness'].default_value=.85
        if m in alpha:tree.links.new(tex.outputs['Alpha'],shader.inputs['Alpha']);m.surface_render_method='BLENDED'
        dest=tree.nodes.new('ShaderNodeOutputMaterial');tree.links.new(shader.outputs[0],dest.inputs['Surface'])
        m.use_backface_culling=True
    for obj in meshes:
        for layer in list(obj.data.uv_layers):
            if layer.name!='RAE_Bake':obj.data.uv_layers.remove(layer)
        obj.data.uv_layers[0].active_render=True
