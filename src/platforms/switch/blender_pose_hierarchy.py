"""Keep scale-compensated prop chains numerically stable in glTF.

SV hides some props with tiny scales while descendants disable scale inheritance.
Serial TRS compensation along such a chain becomes unstable in float32 glTF.
Reparent only those descendants to a stable ancestor and bake evaluated poses.
The body hierarchy and the skin's inverse bind matrices remain intact.
"""
from __future__ import annotations


def retain_auxiliary_skin_roots(doc: dict, root: int) -> None:
    """Keep exporter-created neutral joints under the identity common root.

    These joints are not source pose bones. Retain their original ancestor
    transforms (and attached static meshes) rather than flattening them.
    """
    parents={child:i for i,node in enumerate(doc["nodes"]) for child in node.get("children",[])}
    auxiliary=set()
    for skin in doc.get("skins",[]):
        for joint in skin["joints"]:
            top=joint
            while top in parents and parents[top]!=root:top=parents[top]
            if top!=root and parents.get(top)!=root:auxiliary.add(top)
    for top in sorted(auxiliary):
        doc["nodes"][root].setdefault("children",[]).append(top)
        for scene in doc.get("scenes",[]):
            scene["nodes"]=[i for i in scene["nodes"] if i!=top]


def _node_matrix(node: dict) -> Matrix:
    from mathutils import Matrix, Quaternion, Vector
    if "matrix" in node:
        return Matrix([node["matrix"][row::4] for row in range(4)])
    q = node.get("rotation", (0, 0, 0, 1))
    return Matrix.LocRotScale(Vector(node.get("translation", (0, 0, 0))),
                             Quaternion((q[3], q[0], q[1], q[2])),
                             Vector(node.get("scale", (1, 1, 1))))


def _scale_animated_bones(actions) -> set[str]:
    unstable = set()
    prefix = 'pose.bones['
    for action in actions:
        for layer in action.layers:
            for strip in layer.strips:
                for bag in strip.channelbags:
                    for curve in bag.fcurves:
                        if not curve.data_path.startswith(prefix) or not curve.data_path.endswith('].scale'):
                            continue
                        if any(abs(point.co.y) < .01 or abs(point.co.y) > 100 for point in curve.keyframe_points):
                            # Blender escapes names in RNA paths; all SV source
                            # bone names are ordinary ASCII identifiers.
                            name = curve.data_path[len(prefix) + 1:-len('].scale') - 1]
                            unstable.add(name)
    return unstable


class StablePoseHierarchy:
    def __init__(self, doc: dict, armature, targets: dict, actions, basis: Matrix, *, force_flat=False):
        self.parents = {child: i for i, node in enumerate(doc["nodes"])
                        for child in node.get("children", [])}
        self.rest = {}

        def visit(i):
            if i not in self.rest:
                local = _node_matrix(doc["nodes"][i])
                parent = self.parents.get(i)
                self.rest[i] = visit(parent) @ local if parent is not None else local
            return self.rest[i]

        for i in range(len(doc["nodes"])):
            visit(i)
        unstable = _scale_animated_bones(actions)
        self.adjusted = {}
        flat_root = None
        if force_flat:
            flat_root = len(doc["nodes"])
            doc["nodes"].append({"name":"RAE_SkeletonRoot","children":[]})
            for scene in doc.get("scenes", []):
                scene.setdefault("nodes", []).append(flat_root)
            for skin in doc.get("skins", []):
                skin["skeleton"] = flat_root
        by_name = {bone.name: i for i, bone in targets.items()}
        self.alignments = {i: (basis @ armature.matrix_world @ bone.bone.matrix_local).inverted_safe() @ self.rest[i]
                           for i, bone in targets.items()}
        for i, bone in targets.items():
            if force_flat:
                self.adjusted[i] = None
                continue
            ancestors = []
            parent = bone.parent
            while parent:
                ancestors.append(parent)
                parent = parent.parent
            collapsed = [n for n, ancestor in enumerate(ancestors) if ancestor.name in unstable]
            if not collapsed:
                continue
            index = max(collapsed) + 1
            stable = ancestors[index] if index < len(ancestors) else None
            new_parent = by_name[stable.name] if stable else None
            self.adjusted[i] = new_parent
        for i, new_parent in self.adjusted.items():
            old_parent = self.parents.get(i)
            if old_parent is not None:
                doc["nodes"][old_parent]["children"].remove(i)
                if not doc["nodes"][old_parent]["children"]:
                    doc["nodes"][old_parent].pop("children")
            else:
                for scene in doc.get("scenes", []):
                    if i in scene.get("nodes", []):
                        scene["nodes"].remove(i)
            if new_parent is not None:
                doc["nodes"][new_parent].setdefault("children", []).append(i)
            elif flat_root is not None:
                doc["nodes"][flat_root]["children"].append(i)
            else:
                for scene in doc.get("scenes", []):
                    scene.setdefault("nodes", []).append(i)
            local = self.rest[new_parent].inverted_safe() @ self.rest[i] if new_parent is not None else self.rest[i]
            translation, rotation, scale = local.decompose()
            node = doc["nodes"][i]
            node.pop("matrix", None)
            node.update(translation=list(translation), rotation=[rotation.x, rotation.y, rotation.z, rotation.w], scale=list(scale))
        if flat_root is not None:
            retain_auxiliary_skin_roots(doc,flat_root)
        self.armature = armature
        self.targets = targets
        self.basis = basis
        print(f"RAE: stabilized {len(self.adjusted)} prop descendants", flush=True)

    def local(self, i: int):
        bone = self.targets[i]
        world = self.basis @ self.armature.matrix_world @ bone.matrix @ self.alignments[i]
        parent = self.adjusted[i]
        if parent is None:
            return world
        parent_bone = self.targets[parent]
        parent_world = self.basis @ self.armature.matrix_world @ parent_bone.matrix @ self.alignments[parent]
        return parent_world.inverted_safe() @ world
