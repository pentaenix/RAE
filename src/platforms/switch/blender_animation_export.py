"""Sample evaluated Blender bone poses directly into an existing static GLB.

The static exporter supplies the hierarchy, inverse binds and bone-axis basis.
Evaluated world poses preserve Blender's inherit-scale behavior. This avoids
repeated per-channel dependency-graph work in Blender's general action exporter.
"""
from __future__ import annotations

from array import array
from pathlib import Path
import math
import importlib.util
import sys

import bpy
from mathutils import Matrix

# Load only this island's stdlib-only GLB I/O. The gltf package facade also
# imports preview policy, which is intentionally absent from Blender's runtime.
_spec = importlib.util.spec_from_file_location("_rae_switch_glb_io", Path(__file__).parent / "gltf/glb_io.py")
_io = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = _io
_spec.loader.exec_module(_io)
read_glb = _io.read_glb


def append_bone_animations(path: Path, armature, clips: list[dict], *, source_scale_compensation=False) -> None:
    from blender_pose_hierarchy import StablePoseHierarchy
    glb = read_glb(path)
    doc = glb.json
    blob = bytearray(glb.bin_chunk)
    joints = set(joint for skin in doc.get("skins", []) for joint in skin["joints"])
    bones = {bone.name: bone for bone in armature.pose.bones}
    targets = {i: bones[node["name"]] for i, node in enumerate(doc["nodes"])
               if i in joints and node.get("name") in bones}
    if len(targets) != len(bones):
        raise RuntimeError("Static GLB must preserve every source armature bone")
    # Match Blender's sampled armature exporter: decompose the pose delta
    # before restoring the rest-bone basis. Decomposing the combined matrix
    # instead changes rotations on rigs with non-uniform inherited scaling.
    basis = Matrix.Rotation(-math.pi / 2, 4, "X")
    hierarchy = StablePoseHierarchy(doc, armature, targets,
                                    [bpy.data.actions[clip["name"]] for clip in clips], basis,
                                    force_flat=source_scale_compensation)
    corrections = {i: bone.parent.bone.matrix_local.inverted_safe() @ bone.bone.matrix_local
                   if bone.parent else basis @ bone.bone.matrix_local
                   for i, bone in targets.items()}
    rest_inverse = {i: (bone.parent.bone.matrix_local.inverted_safe() @ bone.bone.matrix_local).inverted_safe()
                    if bone.parent else bone.bone.matrix_local.inverted_safe()
                    for i, bone in targets.items()}

    def accessor(rows, kind: str, *, bounds=False) -> int:
        components = {"SCALAR": 1, "VEC3": 3, "VEC4": 4}[kind]
        flat = [float(value) for row in rows for value in row]
        if not all(math.isfinite(value) for value in flat):
            raise RuntimeError("Animation contains a non-finite evaluated transform")
        payload = array("f", flat).tobytes()
        while len(blob) % 4:
            blob.append(0)
        view = len(doc["bufferViews"])
        doc["bufferViews"].append({"buffer": 0, "byteOffset": len(blob), "byteLength": len(payload)})
        blob.extend(payload)
        result = {"bufferView": view, "componentType": 5126, "count": len(rows), "type": kind}
        if bounds:
            result["min"] = [min(flat[c::components]) for c in range(components)]
            result["max"] = [max(flat[c::components]) for c in range(components)]
        doc["accessors"].append(result)
        return len(doc["accessors"]) - 1

    animations = []
    for clip in clips:
        action = bpy.data.actions.get(clip["name"])
        if action is None:
            raise RuntimeError(f"Action missing: {clip['name']}")
        armature.animation_data.action = action
        if action.slots:
            armature.animation_data.action_slot = action.slots[0]
        for bone in armature.pose.bones:
            bone.matrix_basis = Matrix.Identity(4)
        start, end = map(int, action.frame_range)
        values = {i: {"translation": [], "rotation": [], "scale": []} for i in targets}
        for frame in range(start, end + 1):
            bpy.context.scene.frame_set(frame)
            bpy.context.view_layer.update()
            for i, bone in targets.items():
                if i in hierarchy.adjusted:
                    translation, rotation, scale = hierarchy.local(i).decompose()
                else:
                    local = rest_inverse[i] @ (bone.parent.matrix.inverted_safe() @ bone.matrix
                                               if bone.parent else bone.matrix)
                    translation, rotation, scale = local.decompose()
                    correction = corrections[i]
                    translation = (correction @ Matrix.Translation(translation)).to_translation()
                    rotation = (correction @ rotation.to_matrix().to_4x4()).to_quaternion()
                    scale = (correction @ Matrix.Diagonal((*scale, 1))).to_scale()
                rotation.normalize()
                previous = values[i]["rotation"]
                if previous:
                    old = previous[-1]
                    if sum(a*b for a, b in zip(old, (rotation.x, rotation.y, rotation.z, rotation.w))) < 0:
                        rotation.negate()
                values[i]["translation"].append(tuple(translation))
                values[i]["rotation"].append((rotation.x, rotation.y, rotation.z, rotation.w))
                values[i]["scale"].append(tuple(scale))
        count = end - start + 1
        times = accessor([(frame / clip["fps"],) for frame in range(count)], "SCALAR", bounds=True)
        constant_times = [(0.,), ((count - 1) / clip["fps"],)] if count > 1 else [(0.,)]
        first = accessor(constant_times, "SCALAR", bounds=True)
        animation = {"name": clip["name"], "samplers": [], "channels": []}
        for i, paths in values.items():
            for property_, rows in paths.items():
                constant = all(max(abs(a-b) for a, b in zip(rows[0], row)) < 1e-7 for row in rows)
                output = accessor([rows[0]] * len(constant_times) if constant else rows,
                                  "VEC4" if property_ == "rotation" else "VEC3")
                sampler = len(animation["samplers"])
                animation["samplers"].append({"input": first if constant else times, "output": output,
                                               "interpolation": "LINEAR"})
                animation["channels"].append({"sampler": sampler, "target": {"node": i, "path": property_}})
        animations.append(animation)
        print(f"RAE: sampled {clip['name']}", flush=True)
    armature.animation_data.action = None
    doc["animations"] = animations
    doc["buffers"][0]["byteLength"] = len(blob)
    glb.bin_chunk = bytes(blob)
    glb.write(path)
