"""Blender bridge for pinned GFBMDL geometry and its original color maps."""
from pathlib import Path

import bpy


def transformed_uv(tree, name, values, params=None, *, layer=False):
    if __package__:
        from .swsh_material_uv import blender_color_uv_transform
    else:
        from swsh_material_uv import blender_color_uv_transform
    uv=tree.nodes.new('ShaderNodeUVMap');uv.uv_map=name
    scale,offset=blender_color_uv_transform(values,layer=layer)
    mapping=tree.nodes.new('ShaderNodeMapping')
    mapping.vector_type='POINT'
    mapping.inputs['Scale'].default_value=(*scale,1)
    mapping.inputs['Location'].default_value=(*offset,0)
    tree.links.new(uv.outputs['UV'],mapping.inputs['Vector'])
    split=tree.nodes.new('ShaderNodeSeparateXYZ');tree.links.new(mapping.outputs['Vector'],split.inputs[0])
    combine=tree.nodes.new('ShaderNodeCombineXYZ')
    for i,axis in enumerate(('X','Y')):
        value=split.outputs[i];wrap=getattr(params,'WrapMode'+axis)() if params else 0
        if wrap==2:
            ping=tree.nodes.new('ShaderNodeMath');ping.operation='PINGPONG';ping.inputs[1].default_value=1
            tree.links.new(value,ping.inputs[0]);value=ping.outputs[0]
        if wrap==1:
            clamp=tree.nodes.new('ShaderNodeClamp');tree.links.new(value,clamp.inputs[0]);value=clamp.outputs[0]
        tree.links.new(value,combine.inputs[i])
    return combine.outputs[0]


def load_model(raw: Path, filename: str, rare: bool, material_animation=None,portable_masks=False):
    from pokemon_switch import gfbmdl_import
    from pokemon_switch.GFLib.Model.Model import Model
    source = raw / (Path(filename).stem + "_rare.gfbmdl" if rare else filename)
    data = source.read_bytes()
    model = Model.GetRootAsModel(data, 0)
    original_create = gfbmdl_import.CreateMesh
    def create_named_mesh(_name, mon, index, *args):
        group = next(mon.Groups(i) for i in range(mon.GroupsLength()) if mon.Groups(i).MeshIndex()==index)
        # GFBMDL group bone references are zero-based. The basic upstream
        # importer subtracts one, losing the actual source mesh-group identity.
        name = mon.Bones(group.BoneIndex()).Name().decode()
        return original_create(name,mon,index,*args)
    gfbmdl_import.CreateMesh = create_named_mesh
    try:
        gfbmdl_import.LoadModel(data, source.stem)
    finally:
        gfbmdl_import.CreateMesh = original_create
    # The upstream loader creates the geometry and rig but leaves image nodes
    # unassigned. Bind the exact model's Col0Tex, including the rare model's maps.
    materials = list(bpy.data.materials)
    for index in range(model.MaterialsLength()):
        source_material = model.Materials(index)
        name = source_material.Name().decode()
        material = next(m for m in materials if m.name == name)
        tree = material.node_tree
        tree.nodes.clear()
        shader = tree.nodes.new("ShaderNodeBsdfPrincipled")
        shader.inputs["Roughness"].default_value = 0.85
        output = tree.nodes.new("ShaderNodeOutputMaterial")
        tree.links.new(shader.outputs["BSDF"], output.inputs["Surface"])
        maps = {source_material.TextureMaps(j).Sampler().decode(): source_material.TextureMaps(j).Index()
                for j in range(source_material.TextureMapsLength())}
        samplers={source_material.TextureMaps(j).Sampler().decode():source_material.TextureMaps(j).Params()
                  for j in range(source_material.TextureMapsLength())}
        common = source_material.Common()
        common_values = {common.Values(j).Name().decode():common.Values(j).Value() for j in range(common.ValuesLength())}
        common_flags = {common.Switches(j).Name().decode():common.Switches(j).Value() for j in range(common.SwitchesLength())}
        values = {source_material.Values(j).Name().decode():source_material.Values(j).Value()
                  for j in range(source_material.ValuesLength())}
        if material_animation:
            values.update(material_animation.get(name, {}))
        material["RAE_alpha_blend"] = common_values.get("BlendMode",0)==5
        color_map = next((key for key in ("Col0Tex","L0ColTex","Texture01","TextureMap01") if key in maps),None)
        if color_map:
            texture_name = model.TextureNames(maps[color_map]).decode()
            image_path = raw / (texture_name + ".png")
            if not image_path.is_file():
                raise FileNotFoundError(f"Original color texture not decoded: {texture_name}")
            texture = tree.nodes.new("ShaderNodeTexImage")
            texture.image = bpy.data.images.load(str(image_path), check_existing=True)
            texture.image.pack()
            tree.links.new(transformed_uv(tree,f"UVMap{common_values.get('ColorMapUvIndex',0)+1}",values,samplers[color_map]),
                           texture.inputs["Vector"])
        else:
            colors = {source_material.Colors(j).Name().decode():source_material.Colors(j).Color()
                      for j in range(source_material.ColorsLength())}
            base = colors.get("BaseColor0") or colors.get("ConstantColor0")
            texture = tree.nodes.new("ShaderNodeRGB")
            if base:
                texture.outputs[0].default_value = (base.R(),base.G(),base.B(),1)
            else:
                # Shader-only mask/effect passes have no portable base color.
                # Their complete source remains raw; do not render opaque cards.
                material["RAE_raw_only_effect"] = True
        switches = {source_material.Switches(j).Name().decode():source_material.Switches(j).Value()
                    for j in range(source_material.SwitchesLength())}
        color = texture.outputs["Color"]
        if color_map and switches.get("Layer1Enable") and "LyCol0Tex" in maps:
            layer = tree.nodes.new("ShaderNodeTexImage")
            layer_name = model.TextureNames(maps["LyCol0Tex"]).decode()
            layer.image = bpy.data.images.load(str(raw/(layer_name+".png")),check_existing=True)
            layer.image.pack()
            tree.links.new(transformed_uv(tree,f"UVMap{common_values.get('Layer1UvIdx',0)+1}",values,samplers['LyCol0Tex'],layer=True),
                           layer.inputs["Vector"])
            mix = tree.nodes.new("ShaderNodeMixRGB")
            if common_flags.get("LayerCalcMulti"):
                mix.blend_type = "MULTIPLY"
                mix.inputs[0].default_value = 1
                tree.links.new(color,mix.inputs[1])
                tree.links.new(layer.outputs["Color"],mix.inputs[2])
            else:
                factor=tree.nodes.new('ShaderNodeMath');factor.operation='MULTIPLY'
                tree.links.new(texture.outputs['Alpha'],factor.inputs[0]);factor.inputs[1].default_value=values.get('Layer1OverLerpValue',1)
                tree.links.new(factor.outputs[0],mix.inputs[0])
                tree.links.new(layer.outputs["Color"],mix.inputs[1])
                tree.links.new(color,mix.inputs[2])
            color = mix.outputs["Color"]
        if __package__:
            from .blender_swsh_effects import surface
        else:
            from blender_swsh_effects import surface
        colors = {source_material.Colors(j).Name().decode():source_material.Colors(j).Color() for j in range(source_material.ColorsLength())}
        def effect_uv(prefix,index,override=None,params=None):
            v=override or values
            translated={k.replace(prefix,'Color',1):value for k,value in v.items() if k.startswith(prefix)}
            return transformed_uv(tree,f'UVMap{index+1}',translated,params)
        color,effect_alpha=surface(tree,model,source_material,raw,maps,samplers,values,colors,switches,common_values,color,texture if color_map else None,effect_uv,portable_masks)
        if portable_masks and name.startswith('FireMask'):material['RAE_raw_only_effect']=False
        if effect_alpha is not None:material['RAE_alpha_blend']=True
        tree.links.new(color,shader.inputs["Base Color"])
        # The common bake worker consumes this explicit color-only shader output.
        group_tree = bpy.data.node_groups.new(name+"_portable_color","ShaderNodeTree")
        group_tree.interface.new_socket(name="Color",in_out="INPUT",socket_type="NodeSocketColor")
        group_tree.interface.new_socket(name="BaseColorBake",in_out="OUTPUT",socket_type="NodeSocketShader")
        if material["RAE_alpha_blend"]:
            group_tree.interface.new_socket(name="Alpha",in_out="INPUT",socket_type="NodeSocketFloat")
            group_tree.interface.new_socket(name="AlphaBake",in_out="OUTPUT",socket_type="NodeSocketShader")
        group_input = group_tree.nodes.new("NodeGroupInput")
        diffuse = group_tree.nodes.new("ShaderNodeBsdfDiffuse")
        group_output = group_tree.nodes.new("NodeGroupOutput")
        group_tree.links.new(group_input.outputs["Color"],diffuse.inputs["Color"])
        group_tree.links.new(diffuse.outputs["BSDF"],group_output.inputs["BaseColorBake"])
        if material["RAE_alpha_blend"]:
            alpha_shader = group_tree.nodes.new("ShaderNodeBsdfDiffuse")
            group_tree.links.new(group_input.outputs["Alpha"],alpha_shader.inputs["Color"])
            group_tree.links.new(alpha_shader.outputs["BSDF"],group_output.inputs["AlphaBake"])
        group = tree.nodes.new("ShaderNodeGroup")
        group.node_tree = group_tree
        group.name = "Group"
        tree.links.new(color,group.inputs["Color"])
        if material["RAE_alpha_blend"]:
            if effect_alpha is not None:
                tree.links.new(effect_alpha,group.inputs['Alpha'])
            elif color_map:
                tree.links.new(texture.outputs["Alpha"],group.inputs["Alpha"])
            else:
                group.inputs["Alpha"].default_value=1
        material.use_backface_culling = True
    for obj in bpy.context.scene.objects:
        if obj.type == "MESH":
            remove = {i for i,slot in enumerate(obj.material_slots) if slot.material.get("RAE_raw_only_effect")}
            if remove:
                import bmesh
                mesh = bmesh.new()
                mesh.from_mesh(obj.data)
                bmesh.ops.delete(mesh,geom=[face for face in mesh.faces if face.material_index in remove],context="FACES")
                mesh.to_mesh(obj.data)
                mesh.free()
                if not obj.data.polygons:
                    bpy.data.objects.remove(obj,do_unlink=True)
                    continue
            used=sorted({polygon.material_index for polygon in obj.data.polygons})
            materials=[obj.material_slots[i].material for i in used]
            mapping={old:new for new,old in enumerate(used)}
            indices=[mapping[polygon.material_index] for polygon in obj.data.polygons]
            obj.data.materials.clear()
            for material in materials:
                obj.data.materials.append(material)
            for polygon,index in zip(obj.data.polygons,indices):
                polygon.material_index=index
            # The geometry importer retains the original UV map as its first set.
            obj.data.uv_layers.active_index = 0
            obj.data.uv_layers[0].active_render = True
