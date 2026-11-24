"""Convert model, bind and animated translation units together."""
from pathlib import Path
import struct

from .gltf.glb_io import read_glb


def centimeters_to_meters(path: Path) -> None:
    glb = read_glb(path)
    doc = glb.json
    data = bytearray(glb.bin_chunk)
    accessors = {p["attributes"]["POSITION"] for m in doc.get("meshes", []) for p in m["primitives"]}
    for animation in doc.get("animations", []):
        for channel in animation["channels"]:
            if channel["target"]["path"] == "translation":
                accessors.add(animation["samplers"][channel["sampler"]]["output"])
    binds = {skin["inverseBindMatrices"] for skin in doc.get("skins", [])}
    for index in accessors | binds:
        accessor = doc["accessors"][index]
        if accessor["componentType"] != 5126 or "sparse" in accessor:
            raise ValueError("Unit conversion requires dense float accessors")
        view = doc["bufferViews"][accessor["bufferView"]]
        dimensions = 16 if index in binds else 3
        stride = view.get("byteStride", dimensions * 4)
        base = view.get("byteOffset", 0) + accessor.get("byteOffset", 0)
        for row in range(accessor["count"]):
            for component in (range(12, 15) if index in binds else range(3)):
                offset = base + row * stride + component * 4
                value = struct.unpack_from("<f", data, offset)[0]
                struct.pack_into("<f", data, offset, value * .01)
        for bound in ("min", "max"):
            if bound in accessor:
                accessor[bound] = [v * .01 for v in accessor[bound]]
    for node in doc.get("nodes", []):
        if "translation" in node:
            node["translation"] = [v * .01 for v in node["translation"]]
        if "matrix" in node:
            node["matrix"][12:15] = [v * .01 for v in node["matrix"][12:15]]
    doc.setdefault("extras", {}).setdefault("rae", {})["metersPerSourceUnit"] = .01
    glb.bin_chunk = bytes(data)
    glb.write(path)
