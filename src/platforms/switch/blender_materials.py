"""Bake the Switch importer's layered colors into portable glTF materials.

Executed by Blender, not imported by the RAE UI. Original texture/material files
remain in the raw bundle; source alpha is retained for tagged sprite layers.
"""
from pathlib import Path

import bpy


def _bake_meshes(objects) -> None:
    if not objects:
        return
    bpy.ops.object.select_all(action="DESELECT")
    for obj in objects:
        obj.select_set(True)
    bpy.context.view_layer.objects.active = objects[0]
    bpy.ops.object.bake(type="DIFFUSE", pass_filter={"COLOR"}, margin=8,
                        uv_layer="RAE_Bake")


def bake_base_colors(output: Path, *, batch: bool = False) -> None:
    scene = bpy.context.scene
    scene.render.engine = "CYCLES"
    scene.cycles.device = "CPU"
    scene.cycles.samples = 1
    scene.render.bake.use_clear = False
    meshes = [o for o in scene.objects if o.type == "MESH"]
    # Source UV islands may live outside the first tile. Preserve their repeat
    # sampling explicitly and unwrap a separate destination UV set for baking.
    # Materials shared across meshes need separate target images/UV layouts.
    for obj in meshes:
        bpy.ops.object.select_all(action="DESELECT")
        obj.select_set(True)
        bpy.context.view_layer.objects.active = obj
        source_uv = next(u.name for u in obj.data.uv_layers if u.active_render)
        for slot in obj.material_slots:
            slot.material = slot.material.copy()
            slot.material.name = f"{slot.material.name}_{obj.name.removesuffix('_mesh')}"
            tree = slot.material.node_tree
            uv = tree.nodes.new("ShaderNodeUVMap")
            uv.uv_map = source_uv
            for node in list(tree.nodes):
                if node.type == "TEX_IMAGE" and not node.inputs["Vector"].is_linked:
                    tree.links.new(uv.outputs["UV"], node.inputs["Vector"])
        obj.data.uv_layers.new(name="RAE_Bake")
        obj.data.uv_layers.active_index = len(obj.data.uv_layers) - 1
        bpy.ops.object.mode_set(mode="EDIT")
        bpy.ops.mesh.select_all(action="SELECT")
        bpy.ops.uv.smart_project(island_margin=0.02)
        bpy.ops.object.mode_set(mode="OBJECT")
    materials = {slot.material for obj in meshes for slot in obj.material_slots if slot.material}
    images = {}
    for material in materials:
        if not material.use_nodes:
            raise RuntimeError(f"Material {material.name} has no shader")
        group = material.node_tree.nodes.get("Group")
        if group is None or "BaseColorBake" not in group.outputs:
            raise RuntimeError(f"Material {material.name} lacks a base-color bake output")
        sizes = [max(n.image.size) for n in material.node_tree.nodes
                 if n.type == "TEX_IMAGE" and n.image]
        resolution = min(1024, max(sizes, default=256))
        image = bpy.data.images.new(f"{material.name}_basecolor", resolution, resolution,
                                    alpha=bool(material.get("RAE_alpha_blend")))
        image.alpha_mode = 'CHANNEL_PACKED'
        image.generated_color = (0, 0, 0, 1)
        node = material.node_tree.nodes.new("ShaderNodeTexImage")
        node.image = image
        material.node_tree.nodes.active = node
        surface = material.node_tree.nodes.get("Material Output").inputs["Surface"]
        material.node_tree.links.new(group.outputs["BaseColorBake"], surface)
        images[material] = image
    if batch:
        # Each mesh already owns separate materials/images, so one operator
        # can reuse Cycles setup while writing independent destination atlases.
        _bake_meshes(meshes)
        for obj in meshes:
            obj.data.uv_layers["RAE_Bake"].active_render = True
    else:
        for obj in meshes:
            _bake_meshes([obj])
            obj.data.uv_layers["RAE_Bake"].active_render = True
    output.mkdir(parents=True, exist_ok=True)
    alpha_materials = {m for m in images if m.get("RAE_alpha_blend")}
    if alpha_materials:
        import numpy as np
        colors = {m:np.array(images[m].pixels[:],dtype=np.float32).reshape((-1,4)) for m in alpha_materials}
        for material in alpha_materials:
            tree = material.node_tree
            tree.links.new(tree.nodes["Group"].outputs["AlphaBake"],tree.nodes["Material Output"].inputs["Surface"])
        alpha_meshes = [obj for obj in meshes if any(slot.material in alpha_materials for slot in obj.material_slots)]
        if batch:
            _bake_meshes(alpha_meshes)
        else:
            for obj in alpha_meshes:
                _bake_meshes([obj])
        for material,pixels in colors.items():
            pixels[:,3]=np.array(images[material].pixels[:],dtype=np.float32).reshape((-1,4))[:,0]
            images[material].pixels.foreach_set(pixels.ravel())
            images[material].update()
    for material, image in images.items():
        image.filepath_raw = str(output / f"{material.name}.png")
        image.file_format = "PNG"
        image.save()
        image.pack()
        nodes = material.node_tree.nodes
        nodes.clear()
        texture = nodes.new("ShaderNodeTexImage")
        texture.image = image
        shader = nodes.new("ShaderNodeBsdfPrincipled")
        shader.inputs["Metallic"].default_value = 0
        shader.inputs["Roughness"].default_value = 0.85
        target = nodes.new("ShaderNodeOutputMaterial")
        material.node_tree.links.new(texture.outputs["Color"], shader.inputs["Base Color"])
        if material in alpha_materials:
            material.node_tree.links.new(texture.outputs["Alpha"],shader.inputs["Alpha"])
            material.surface_render_method="BLENDED"
        material.node_tree.links.new(shader.outputs["BSDF"], target.inputs["Surface"])
        material.use_backface_culling = True
    # Portable consumers, including Resort, use TEXCOORD_0 for base colors.
    # Source UVs remain recoverable in raw/; only the baked UV is needed here.
    for obj in meshes:
        for layer in list(obj.data.uv_layers):
            if layer.name != "RAE_Bake":
                obj.data.uv_layers.remove(layer)
        obj.data.uv_layers.active_index = 0
        obj.data.uv_layers[0].active_render = True
