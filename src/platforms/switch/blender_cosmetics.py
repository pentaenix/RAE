"""Bake material-only cosmetic selectors without reimporting skeletal clips."""
from __future__ import annotations
import contextlib
import io
import json
from pathlib import Path
import sys

import bpy


def main(job):
    deps=Path(job["dependencies"])
    sys.path[:0]=[str(deps/"python"),str(deps),str(Path(__file__).parent)]
    from pokemon_switch import PokemonSwitch
    from blender_materials import bake_base_colors
    def offline(*args,**kwargs):raise OSError("Pinned offline shader")
    PokemonSwitch.requests.get=offline
    for color in ("normal","rare"):
        for form,values in enumerate(job["cosmetics"][color]):
            bpy.ops.wm.read_factory_settings(use_empty=True)
            with contextlib.redirect_stdout(io.StringIO()):
                PokemonSwitch.from_trmdlsv(job["raw"],job["modelFile"],color=="rare",False,True,False,False,False)
            for value in values:
                mesh=bpy.data.objects.get(value["mesh"].removesuffix("_shape"))
                if mesh is None:raise ValueError("Cosmetic mapper mesh missing: "+value["mesh"])
                material=next((s.material for s in mesh.material_slots
                    if s.material.name.split(".")[0]==value["material"]),None)
                if material is None:raise ValueError("Cosmetic mapper material missing")
                group=material.node_tree.nodes["Group"]
                group.inputs[value["parameter"]].default_value=value["value"]
            target=Path(job["output"])/f"cosmetic_{form:02}_{color}.glb"
            bake_base_colors(Path(job["output"])/f"cosmetic_{form:02}_{color}_textures")
            bpy.ops.object.select_all(action="SELECT")
            bpy.ops.export_scene.gltf(filepath=str(target),export_format="GLB",use_selection=True,
                export_animations=False,export_skins=True,export_def_bones=False,export_yup=True,
                export_cameras=False,export_lights=False)


if __name__=="__main__":
    main(json.loads(Path(sys.argv[sys.argv.index("--")+1]).read_text()))
