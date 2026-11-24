"""Build preview-only environments for New Pokémon Snap courses."""
from __future__ import annotations

import math
import struct
from pathlib import Path

from .container import SwitchRom
from .flatbuf import child_table, read_string, read_table_vector, root_offset, table_fields, u32, vector_len, vector_offset
from .gltf.glb_io import GlbData
from .snap_courses import SNAP_COURSES, SnapCourse
from .snap_drp import DrpPack
from .snap_materials import read_model_bindings, read_texture_slots


def _scene_tables(data, field):
    if field is None or vector_len(data, vector_offset(data, field)) > 128:
        raise ValueError("Unexpected Snap environment table size")
    return read_table_vector(data, field)


def _placements(data: bytes, course: SnapCourse) -> dict[str, dict]:
    root = table_fields(data, root_offset(data))
    version = root.get(0)
    if version is None or u32(data, version) != 6:
        raise ValueError("Unsupported Snap environment scene version")
    placements = {}
    for node in _scene_tables(data, root.get(2)):
        for component in _scene_tables(data, node.get(0)):
            tag = component.get(0)
            if tag is None or data[tag] != 6:
                continue
            placed = child_table(data, component.get(5))
            if placed is None or (name_offset := placed.get(1)) is None:
                continue
            name = read_string(data, name_offset)
            if not name.startswith(course.model_prefix):
                continue
            if name in placements:
                raise ValueError(f"Duplicate Snap environment placement: {name}")
            transform = {}
            for field, key, fmt in ((3, "translation", "<3f"), (4, "rotation", "<4f"), (5, "scale", "<3f")):
                offset = placed.get(field)
                if offset is None:
                    raise ValueError(f"Missing Snap environment {key}: {name}")
                values = struct.unpack_from(fmt, data, offset)
                if not all(math.isfinite(value) for value in values):
                    raise ValueError(f"Invalid Snap environment {key}: {name}")
                transform[key] = values
            placements[name] = transform
    if course.backdrop not in placements or len(placements) < 2:
        raise ValueError(f"Incomplete environment in {course.label}")
    return placements


def _preview_material(label, shape, slots, texture, *, backdrop, shadow):
    base = slots.get("baseColorTexture")
    wave = slots.get("waveNormalTexture")
    water = bool(wave) and base in (None, ".nutexb")
    cutout = label.endswith(("_weedA", "_seaweedA_00"))
    surface = "backdrop" if backdrop else "water" if water else "terrain"
    color = [0.33, 0.50, 0.65, 1] if backdrop else [0.34, 0.54, 0.82, 1]
    pbr = {"baseColorFactor": color, "metallicFactor": 0, "roughnessFactor": 0.9}
    material = {"name": f"{label}/{shape}", "doubleSided": True, "pbrMetallicRoughness": pbr,
                "extras": {"rae": {"snapSurface": surface}}}
    if water:
        pbr.update(baseColorFactor=[0.035, 0.22, 0.35, 0.24], roughnessFactor=0.5)
        material["alphaMode"] = "BLEND"
    else:
        pbr["baseColorTexture"] = {"index": texture(slots["baseColorTexture"],
                                                     "cutout" if cutout else "color", clamp=backdrop)}
    if cutout:
        material.update(alphaMode="MASK", alphaCutoff=0.45)
    if backdrop:
        material["extensions"] = {"KHR_materials_unlit": {}}
        return material
    normal = wave if water else slots.get("normalTexture")
    if normal and normal != ".nutexb":
        material["normalTexture"] = {"index": texture(normal, "normal"), "scale": 0.85}
    if shadow:
        material["occlusionTexture"] = {
            "index": texture(shadow, "shadow", clamp=True), "texCoord": 1, "strength": 0.8,
        }
    if (emissive := slots.get("emissiveTexture")) and emissive != ".nutexb":
        material["emissiveTexture"] = {"index": texture(emissive, "color")}
        material["emissiveFactor"] = [0.33, 0.42, 0.55]
    return material


def _layer_textures(slots, texture):
    layers = {}
    for key, slot, role in (
        ("color", "blendBaseColorTexture", "color"),
        ("normal", "blendNormalTexture", "normal"),
        ("emissive", "blendEmissiveTexture", "color"),
    ):
        if (name := slots.get(slot)) and name != ".nutexb":
            layers[key] = texture(name, role)
    return layers


def _layout_glb(pack: DrpPack, course: SnapCourse, progress=None) -> GlbData:
    import numpy as np

    from .snap_mesh import read_static_meshes
    from .snap_textures import texture_png

    members = {(entry.name, entry.type_hash): entry for entry in pack.members()}
    layout = members.get((course.scene_name, 0xF59A44EB))
    if layout is None:
        raise ValueError(f"{course.label} environment is missing from the course pack")
    placements = _placements(pack.payload(layout), course)
    nodes, meshes, materials, views, accessors = [], [], [], [], []
    textures, images = [], []
    texture_indices = {}
    shadows = {}
    for name, kind in members:
        if kind == 0x5C156DBC and name.startswith(f"{course.scene_name}^") and name.endswith("^Shadow.nutexb"):
            _, model, _, shape, subindex, _ = name.split("^")
            # The source shadow table appends a placement ordinal to the model name.
            shadows[model.removesuffix("1"), shape, int(subindex)] = name
    payload = bytearray()

    def buffer_view(data: bytes) -> int:
        payload.extend(b"\0" * (-len(payload) % 4))
        views.append({"buffer": 0, "byteOffset": len(payload), "byteLength": len(data)})
        payload.extend(data)
        return len(views) - 1

    def accessor(values: np.ndarray, component: int, kind: str, *, position: bool = False) -> int:
        view = buffer_view(values.tobytes())
        spec = {"bufferView": view, "componentType": component, "count": len(values), "type": kind}
        if position:
            spec.update(min=values.min(axis=0).tolist(), max=values.max(axis=0).tolist())
        accessors.append(spec)
        return len(accessors) - 1

    def member_data(name: str, kind: int) -> bytes:
        entry = members.get((name, kind))
        if entry is None:
            raise ValueError(f"{course.label} resource is missing: {name}")
        return pack.payload(entry)

    def texture(name: str, role: str, *, clamp: bool = False) -> int:
        key = name, role, clamp
        if key not in texture_indices:
            limit = min(512, course.texture_limit) if role == "shadow" and course.texture_limit else course.texture_limit
            png = texture_png(member_data(name, 0x5C156DBC), role, size_limit=limit)
            images.append({"name": name, "bufferView": buffer_view(png), "mimeType": "image/png"})
            texture_indices[key] = len(textures)
            textures.append({"source": len(images) - 1, "sampler": int(clamp)})
        return texture_indices[key]

    texture_slots = {}
    for index, (name, transform) in enumerate(placements.items(), 1):
        if progress:
            progress(f"Switch: preparing {course.label} ({index}/{len(placements)})…")
        header = f"{name}_LightmapUV.nusrcmdlb"
        if (header, 0x3F86D270) not in members:
            header = f"{name}.nusrcmdlb"
        mesh_file, bindings = read_model_bindings(member_data(header, 0x3F86D270))
        parts = read_static_meshes(member_data(mesh_file, 0x236DB83A))
        children = []
        for part in parts:
            shape = part.name, part.subindex
            label = bindings[shape]
            if label not in texture_slots:
                texture_slots[label] = read_texture_slots(member_data(f"{label}.matinstb", 0x623D9D06))
            slots = texture_slots[label]
            material = _preview_material(
                label, part.name, slots, texture,
                backdrop=name == course.backdrop,
                shadow=shadows.get((name, *shape)) if part.lightmap_uv is not None else None,
            )
            normal_lengths = np.linalg.norm(part.normals, axis=1, keepdims=True)
            normals = np.zeros(part.normals.shape, dtype="<f4")
            normals[:, 1] = 1
            np.divide(part.normals, normal_lengths, out=normals, where=normal_lengths > 1e-8)
            primitive = {
                "attributes": {"POSITION": accessor(part.positions, 5126, "VEC3", position=True),
                               "NORMAL": accessor(normals, 5126, "VEC3"),
                               "TEXCOORD_0": accessor(part.uv, 5126, "VEC2")},
                "indices": accessor(part.indices, 5123 if part.indices.itemsize == 2 else 5125, "SCALAR"),
                "material": len(materials),
            }
            if part.lightmap_uv is not None:
                primitive["attributes"]["TEXCOORD_1"] = accessor(part.lightmap_uv, 5126, "VEC2")
            if part.layer_mask is not None and part.layer_mask.any() and (layers := _layer_textures(slots, texture)):
                material["extras"]["rae"]["snapLayers"] = layers
                primitive["attributes"]["_SNAP_LAYER_MASK"] = accessor(part.layer_mask, 5126, "SCALAR")
            materials.append(material)
            children.append(len(nodes))
            nodes.append({"name": part.name, "mesh": len(meshes)})
            meshes.append({"name": part.name, "primitives": [primitive]})
        placements[name] = {"name": name, "children": children, **transform}

    roots = list(range(len(nodes), len(nodes) + len(placements)))
    nodes.extend(placements.values())
    return GlbData({
        "asset": {"version": "2.0", "generator": "RAE Switch scene preview"},
        "extensionsUsed": ["KHR_materials_unlit"],
        "extras": {"rae": {"platform": "switch", "freeCamera": {
            "start": course.start, "target": course.target, "background": course.background, "fog": course.fog,
        }}},
        "scene": 0, "scenes": [{"name": course.label, "nodes": roots}],
        "nodes": nodes, "meshes": meshes, "materials": materials,
        "textures": textures, "images": images,
        "samplers": [{"wrapS": wrap, "wrapT": wrap, "magFilter": 9729, "minFilter": 9987} for wrap in (10497, 33071)],
        "buffers": [{"byteLength": len(payload)}], "bufferViews": views, "accessors": accessors,
    }, bytes(payload))


def build_snap_course_preview(descriptor: dict, out_path: Path, progress=None) -> Path:
    course = SNAP_COURSES.get(descriptor.get("romfs_path"))
    if course is None:
        raise ValueError("Unrecognized Snap preview course")
    if progress:
        progress(f"Switch: reading {course.label} terrain…")
    with SwitchRom(descriptor["rom"]) as rom:
        source = next((entry for entry in rom.romfs_files() if entry.path == course.pack_path), None)
        if source is None:
            raise ValueError(f"This ROM does not contain the {course.label} course pack")
        pack = DrpPack(lambda offset, length: rom.read_file(source, offset, length), source.size)
        glb = _layout_glb(pack, course, progress)
    glb.write(out_path)
    return out_path
