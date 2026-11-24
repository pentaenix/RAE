"""Remove superseded appearance resources while preserving rig/clip buffers."""
from copy import deepcopy

from .gltf.glb_io import read_glb


def compact_appearances(path):
    glb=read_glb(path)
    doc=glb.json
    if len(doc.get("buffers",[]))!=1:
        raise ValueError("Compaction requires one embedded buffer")
    used={p["material"] for m in doc["meshes"] for p in m["primitives"]}
    pending=list(used)
    while pending:
        rae=doc["materials"][pending.pop()].get("extras",{}).get("rae",{})
        refs=list(rae.get("formMaterialIndices",{}).values())
        if "shinyMaterialIndex" in rae:refs.append(rae["shinyMaterialIndex"])
        for index in refs:
            if index not in used:used.add(index);pending.append(index)
    mapping={old:new for new,old in enumerate(sorted(used))}
    materials=[deepcopy(doc["materials"][old]) for old in sorted(used)]
    textures=set()
    for material in materials:
        rae=material.get("extras",{}).get("rae",{})
        if "shinyMaterialIndex" in rae:rae["shinyMaterialIndex"]=mapping[rae["shinyMaterialIndex"]]
        if "formMaterialIndices" in rae:rae["formMaterialIndices"]={k:mapping[v] for k,v in rae["formMaterialIndices"].items()}
        for holder in (material,material.get("pbrMetallicRoughness",{})):
            for key,value in holder.items():
                if key.endswith("Texture") and isinstance(value,dict) and "index" in value:textures.add(value["index"])
    texmap={old:new for new,old in enumerate(sorted(textures))}
    for material in materials:
        for holder in (material,material.get("pbrMetallicRoughness",{})):
            for key,value in holder.items():
                if key.endswith("Texture") and isinstance(value,dict) and "index" in value:value["index"]=texmap[value["index"]]
    for mesh in doc["meshes"]:
        for primitive in mesh["primitives"]:primitive["material"]=mapping[primitive["material"]]
    doc["materials"]=materials
    doc["textures"]=[deepcopy(doc["textures"][i]) for i in sorted(textures)]
    images=sorted({t["source"] for t in doc["textures"]})
    imagemap={old:new for new,old in enumerate(images)}
    for texture in doc["textures"]:texture["source"]=imagemap[texture["source"]]
    doc["images"]=[doc["images"][i] for i in images]
    views={i["bufferView"] for i in doc["images"]}
    view_holders=list(doc["images"])
    for accessor in doc.get("accessors",[]):
        if "bufferView" in accessor:views.add(accessor["bufferView"]);view_holders.append(accessor)
        for value in accessor.get("sparse",{}).values():
            if isinstance(value,dict) and "bufferView" in value:views.add(value["bufferView"]);view_holders.append(value)
    viewmap={old:new for new,old in enumerate(sorted(views))}
    blob=bytearray();output=[]
    for old in sorted(views):
        view=deepcopy(doc["bufferViews"][old]);start=view.get("byteOffset",0)
        while len(blob)%4:blob.append(0)
        view["byteOffset"]=len(blob);output.append(view)
        blob.extend(glb.bin_chunk[start:start+view["byteLength"]])
    for holder in view_holders:holder["bufferView"]=viewmap[holder["bufferView"]]
    doc["bufferViews"]=output
    doc["buffers"][0]["byteLength"]=len(blob)
    glb.bin_chunk=bytes(blob)
    glb.write(path)
