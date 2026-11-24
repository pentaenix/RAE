"""Blender-only source shiny bake, isolated from normal rig/action import."""
import contextlib
import io
from pathlib import Path

import bpy


def export_shiny(job, importer):
    from blender_materials import bake_base_colors
    raw = Path(job["raw"])
    with contextlib.redirect_stdout(io.StringIO()):
        if job.get("sourceFormat") == "gfbmdl":
            from blender_swsh import load_model
            load_model(raw, job["modelFile"], True)
        else:
            importer.from_trmdlsv(str(raw), job.get("modelFile", job["assetId"] + ".trmdl"),
                                 True, False, True, False, False, False)
    bake_base_colors(Path(job["output"]) / "textures_shiny")
    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.export_scene.gltf(filepath=str(Path(job["output"]) / "shiny.glb"),
        export_format="GLB", use_selection=True, export_animations=False,
        export_skins=True, export_def_bones=False, export_yup=True,
        export_cameras=False, export_lights=False)
    bpy.ops.wm.read_factory_settings(use_empty=True)
