"""Rebake static Sword materials without reimporting skeletal actions."""
import contextlib
import io
import json
from pathlib import Path
import sys

import bpy


def main(job):
    deps=Path(job["dependencies"])
    sys.path[:0]=[str(deps/"python"),str(deps),str(Path(__file__).parent)]
    from blender_swsh import load_model
    from blender_materials import bake_base_colors
    prefix=job.get('appearancePrefix','appearance')
    for rare in (False,True):
        bpy.ops.wm.read_factory_settings(use_empty=True)
        with contextlib.redirect_stdout(io.StringIO()):
            load_model(Path(job["raw"]),job["modelFile"],rare)
        color="rare" if rare else "normal"
        bake_base_colors(Path(job["output"])/(prefix+"_"+color+"_textures"))
        bpy.ops.object.select_all(action="SELECT")
        bpy.ops.export_scene.gltf(filepath=str(Path(job["output"])/(prefix+"_"+color+".glb")),
            export_format="GLB",use_selection=True,export_animations=False,export_skins=True,
            export_def_bones=False,export_yup=True,export_cameras=False,export_lights=False)


if __name__=="__main__":
    main(json.loads(Path(sys.argv[sys.argv.index("--")+1]).read_text()))
