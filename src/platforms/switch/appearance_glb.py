"""Attach source-authentic shiny materials to an animated normal GLB.

Meshes, UVs and primitive assignments must match before sharing the normal rig.
The Attend material-index extension selects colors without duplicating clips.
"""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from pathlib import Path
import re
import struct

from .gltf.glb_io import read_glb


def _attribute_bytes(glb, index):
    accessor = glb.json["accessors"][index]
    view = glb.json["bufferViews"][accessor["bufferView"]]
    if "byteStride" in view or accessor.get("byteOffset", 0) or "sparse" in accessor:
        raise ValueError("Variant geometry requires dense, separate attribute buffers")
    start = view.get("byteOffset", 0)
    return glb.bin_chunk[start:start + view["byteLength"]]


def _primitive_materials(glb):
    result = {}
    for mesh in glb.json["meshes"]:
        for number, primitive in enumerate(mesh["primitives"]):
            attrs = primitive["attributes"]
            # Mesh labels can differ between importer revisions. Match actual
            # geometry instead, retaining the ambiguity guard below. Blender's
            # equivalent normal/rare rigs sometimes emit subnormal zero noise.
            positions = _attribute_bytes(glb, attrs["POSITION"])
            positions = b"".join(struct.pack("<f", 0.0 if abs(v)<1e-12 else v)
                                 for (v,) in struct.iter_unpack("<f",positions))
            key = (mesh["name"],number,hashlib.sha256(positions).digest(),
                   hashlib.sha256(_attribute_bytes(glb,attrs["TEXCOORD_0"])).digest(),
                   hashlib.sha256(_attribute_bytes(glb, primitive["indices"])).digest())
            material = primitive["material"]
            if key in result and result[key] != material:
                raise ValueError("Ambiguous variant primitive/material mapping")
            result[key] = material
    return result


def _material_identity(glb,index):
    """Shared geometry may use equivalent per-mesh bake material copies."""
    material=deepcopy(glb.json['materials'][index]);name=material.pop('name','')
    semantic=re.split(r'\.\d{3}(?:_|$)',name,maxsplit=1)[0].removesuffix('_shiny')
    for holder in (material,material.get('pbrMetallicRoughness',{})):
        for key,value in holder.items():
            if not key.endswith('Texture') or not isinstance(value,dict) or 'index' not in value:continue
            texture=glb.json['textures'][value['index']];image=glb.json['images'][texture['source']]
            if 'bufferView' not in image:raise ValueError('Variant texture must be embedded')
            view=glb.json['bufferViews'][image['bufferView']];start=view.get('byteOffset',0)
            value['index']=hashlib.sha256(glb.bin_chunk[start:start+view['byteLength']]).hexdigest()
            value['sampler']=glb.json.get('samplers',[])[texture['sampler']] if 'sampler' in texture else {}
    return semantic,json.dumps(material,sort_keys=True)


def _append_variant(normal_path: Path, shiny_path: Path, *, form_id=None, shiny_for=None) -> dict:
    normal, shiny = read_glb(normal_path), read_glb(shiny_path)
    doc, source = normal.json, shiny.json
    normals, shinies = _primitive_materials(normal), _primitive_materials(shiny)
    # Prefer exact identities for overlapping alternatives (Alcremie's mouths).
    # Older exports with corrected group labels may fall back to an unambiguous
    # geometry match, never to ordering or a guessed material assignment.
    by_geometry = {}
    for key,index in shinies.items():
        by_geometry.setdefault(key[2:],set()).add(index)
    if len(normals)!=len(shinies) or {k[2:] for k in normals}!={k[2:] for k in shinies}:
        raise ValueError("Normal/shiny positions or baked UVs differ; cannot share geometry")
    links = {}
    for key, index in normals.items():
        candidates = {shinies[key]} if key in shinies else by_geometry[key[2:]]
        if len(candidates)!=1 and len({_material_identity(shiny,i) for i in candidates})!=1:
            raise ValueError("Ambiguous variant primitive/material mapping")
        candidate = min(candidates)
        if index in links and links[index] != candidate:
            raise ValueError("Normal material has inconsistent shiny counterparts")
        links[index] = candidate
    data = bytearray(normal.bin_chunk)
    image_map, texture_map, material_map = {}, {}, {}

    def image(index):
        if index not in image_map:
            item = deepcopy(source["images"][index])
            if "uri" in item:
                raise ValueError("Shiny image must be embedded")
            view = source["bufferViews"][item["bufferView"]]
            start = view.get("byteOffset", 0)
            payload = shiny.bin_chunk[start:start + view["byteLength"]]
            while len(data) % 4:
                data.append(0)
            item["bufferView"] = len(doc["bufferViews"])
            doc["bufferViews"].append({"buffer": 0, "byteOffset": len(data), "byteLength": len(payload)})
            data.extend(payload)
            image_map[index] = len(doc["images"])
            doc["images"].append(item)
        return image_map[index]

    def texture(index):
        if index not in texture_map:
            item = deepcopy(source["textures"][index])
            item["source"] = image(item["source"])
            if "sampler" in item:
                sampler = source["samplers"][item["sampler"]]
                samplers = doc.setdefault("samplers", [])
                if sampler not in samplers:
                    samplers.append(deepcopy(sampler))
                item["sampler"] = samplers.index(sampler)
            texture_map[index] = len(doc["textures"])
            doc["textures"].append(item)
        return texture_map[index]

    for normal_index, shiny_index in links.items():
        if shiny_index not in material_map:
            item = deepcopy(source["materials"][shiny_index])
            if item.get("extensions"):
                raise ValueError("Bake variant material extensions before merging")
            for holder in (item, item.get("pbrMetallicRoughness", {})):
                for key, value in holder.items():
                    if key.endswith("Texture") and isinstance(value, dict) and "index" in value:
                        value["index"] = texture(value["index"])
            item["name"] = item.get("name", "material") + "_shiny"
            item.setdefault("extras", {})["rae"] = {"platform": "switch", "schemaVersion": 1,
                "renderClass":{"BLEND":"blend","MASK":"mask"}.get(item.get("alphaMode"),"opaque")}
            material_map[shiny_index] = len(doc["materials"])
            doc["materials"].append(item)
        parent = doc["materials"][shiny_for.get(normal_index,normal_index) if shiny_for else normal_index]
        extras = parent.setdefault("extras", {}).setdefault("rae", {})
        if form_id is None:
            extras["shinyMaterialIndex"] = material_map[shiny_index]
        else:
            extras.setdefault("formMaterialIndices", {})[form_id] = material_map[shiny_index]
    rae = doc.setdefault("extras", {}).setdefault("rae", {})
    rae["textureVariants"] = {"default": "normal", "options": [{"id": "normal", "label": "Normal"}, {"id": "shiny", "label": "Shiny"}]}
    appearance = rae.setdefault("appearanceVariants", {"default":{},"axes":[]})
    appearance["default"]["texture"] = "normal"
    appearance["axes"] = [axis for axis in appearance["axes"] if axis["id"] != "texture"] + [
        {"id": "texture", "label": "Color", **rae["textureVariants"]}]
    rae["shinySource"] = "original-game-materials"
    doc["buffers"][0]["byteLength"] = len(data)
    normal.bin_chunk = bytes(data)
    normal.write(normal_path)
    return {index:material_map[other] for index,other in links.items()}


def add_shiny_variant(normal_path: Path, shiny_path: Path) -> dict:
    links = _append_variant(normal_path,shiny_path)
    return {"shinyMaterials":len(links),"variantGeometryVerified":True}


def replace_base_materials(path: Path, source: Path) -> None:
    links=_append_variant(path,source,form_id="__source_default__")
    glb=read_glb(path)
    for mesh in glb.json["meshes"]:
        for primitive in mesh["primitives"]:
            primitive["material"]=links[primitive["material"]]
    for old in links:
        forms=glb.json["materials"][old]["extras"]["rae"]["formMaterialIndices"]
        forms.pop("__source_default__")
    glb.write(path)


def add_cosmetic_variant(path: Path, normal: Path, shiny: Path, form_id: str) -> None:
    links = _append_variant(path,normal,form_id=form_id)
    _append_variant(path,shiny,shiny_for=links)


def set_cosmetic_axis(path: Path, labels: list[str]) -> None:
    glb = read_glb(path)
    rae = glb.json["extras"]["rae"]
    options = [{"id":f"{i:02}","label":label} for i,label in enumerate(labels)]
    rae["speciesVariants"] = {"default":{"form":"00","shiny":False},"forms":options}
    rae["appearanceVariants"]["default"]["form"] = "00"
    rae["appearanceVariants"]["axes"] = [a for a in rae["appearanceVariants"]["axes"] if a["id"]!="form"] + [
        {"id":"form","label":"Form","default":"00","options":options}]
    glb.write(path)
