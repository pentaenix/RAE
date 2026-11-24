"""Offline Blender worker for the separately installed Switch importer.

Run via pokemon_export, which supplies a JSON job after extracting the ROM.
Nothing is registered in the user's Blender preferences or startup file.
"""
from __future__ import annotations

import contextlib
import io
import json
import sys
from pathlib import Path

import bpy
from mathutils import Matrix


def convert(job: dict) -> None:
    dependency_root = Path(job["dependencies"])
    sys.path[:0] = [str(dependency_root / "python"), str(dependency_root), str(Path(__file__).parent)]
    from pokemon_switch import PokemonSwitch, gfbanm_importer
    from blender_materials import bake_base_colors

    # Upstream otherwise refreshes its shader from the network during import.
    def offline(*_args, **_kwargs):
        raise OSError("RAE conversion uses the pinned local shader")

    PokemonSwitch.requests.get = offline
    raw = Path(job["raw"])
    output = Path(job["output"])
    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.object.delete(use_global=False)
    if job.get("includeShiny"):
        from blender_shiny import export_shiny
        export_shiny(job, PokemonSwitch)
    with contextlib.redirect_stdout(io.StringIO()):
        if job.get("sourceFormat") == "gfbmdl":
            from blender_swsh import load_model
            load_model(raw, job["modelFile"], False)
        else:
            PokemonSwitch.from_trmdlsv(str(raw), job.get("modelFile", job["assetId"] + ".trmdl"),
                                      False, False, True, False, False, False)
    armatures = [o for o in bpy.context.scene.objects if o.type == "ARMATURE"]
    meshes = [o for o in bpy.context.scene.objects if o.type == "MESH"]
    if len(armatures) != 1 or not meshes:
        raise RuntimeError("Importer did not produce one rig and its meshes")
    armature = armatures[0]
    print(f"RAE: {len(armature.data.bones)} bones, {len(meshes)} meshes", flush=True)
    bake_base_colors(output / "textures")
    bpy.ops.object.select_all(action="DESELECT")
    armature.select_set(True)
    bpy.context.view_layer.objects.active = armature
    clips = []
    material_only = []
    for path in sorted(raw.glob("*.tranm")) + sorted(raw.glob("*.gfbanm")):
        if job.get("sourceFormat") == "gfbmdl":
            from pokemon_switch.GFLib.Anim.Animation import AnimationT
            source_animation = AnimationT.InitFromPackedBuf(bytearray(path.read_bytes()), 0)
            if source_animation.skeleton is None:
                material_only.append(path.name)
                continue
        before = set(bpy.data.actions)
        with contextlib.redirect_stdout(io.StringIO()):
            gfbanm_importer.import_animation(bpy.context, str(path), False, 0, False, False)
        created = set(bpy.data.actions) - before
        if len(created) != 1:
            raise RuntimeError(f"Animation did not produce one action: {path.name}")
        action = created.pop()
        start, end = action.frame_range
        clips.append({"name": action.name, "source": path.name,
                      "frames": int(end - start + 1), "fps": bpy.context.scene.render.fps})
        print(f"RAE: animation {len(clips)} {path.name}", flush=True)
    if not clips:
        raise RuntimeError("No skeletal animations found")
    if len({clip["fps"] for clip in clips}) != 1:
        raise RuntimeError("Mixed clip frame rates require resampling before GLB export")
    armature.animation_data.action = None
    for bone in armature.pose.bones:
        bone.matrix_basis = Matrix.Identity(4)
    bpy.context.view_layer.update()
    bpy.context.scene.frame_start = 0
    bpy.context.scene.frame_end = max(c["frames"] for c in clips) - 1
    bpy.ops.object.select_all(action="SELECT")
    # Preserve editable source separately; runtime GLB has embedded textures.
    bpy.ops.wm.save_as_mainfile(filepath=str(Path(job["glb"]).with_suffix(".blend")))
    writer = job.get("animationWriter", "evaluated_bone_poses")
    options = dict(filepath=job["glb"], export_format="GLB", use_selection=True,
                   export_skins=True, export_yup=True, export_cameras=False, export_lights=False)
    if writer == "evaluated_bone_poses":
        from blender_animation_export import append_bone_animations
        result = bpy.ops.export_scene.gltf(**options, export_animations=False, export_def_bones=False)
        if "FINISHED" in result:
            append_bone_animations(Path(job["glb"]), armature, clips,
                                   source_scale_compensation=job.get("sourceScaleCompensation",job.get("sourceFormat") == "gfbmdl"))
    elif writer == "blender_actions":
        result = bpy.ops.export_scene.gltf(**options, export_animations=True, export_animation_mode="ACTIONS",
            export_force_sampling=True, export_frame_range=False, export_anim_single_armature=True)
    else:
        raise ValueError(f"Unknown animation writer: {writer}")
    if "FINISHED" not in result:
        raise RuntimeError("Blender GLB export failed")
    (output / "animation_manifest.json").write_text(json.dumps({
        "species": job["species"], "name": job["name"], "assetId": job["assetId"],
        "bones": len(armature.data.bones), "meshes": len(meshes), "animations": clips,
        "animationWriter": writer,
        "materialOnlyAnimations": material_only,
        "limitations": ["Base colors baked; original game lighting is not reproduced.",
                         "Material/UV animation (TRACM) and effects (TRAEF) remain raw only."],
    }, indent=2) + "\n")


if __name__ == "__main__":
    job_path = Path(sys.argv[sys.argv.index("--") + 1])
    convert(json.loads(job_path.read_text()))
