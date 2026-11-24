"""Repeatable single-form animated export, using local console keys and Blender.

python -m rae.platforms.switch.pokemon_export --help
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
from pathlib import Path

from .gltf.glb_io import read_glb
from .pokemon_bundle import extract_pokemon_bundle

IMPORTER_COMMIT = "bb597581916c7407385afb5461efe4d2ae2f38f9"


def check_dependencies(dependencies: Path, blender: str) -> str:
    importer = dependencies / "pokemon_switch"
    if not (importer / "PokemonSwitch.py").is_file() or not (importer / "SCVIShader.blend").is_file():
        raise FileNotFoundError("Install the pinned Switch importer; see the Switch README")
    commit = subprocess.check_output(["git", "-C", str(importer), "rev-parse", "HEAD"], text=True).strip()
    if commit != IMPORTER_COMMIT:
        raise ValueError(f"Expected Switch importer commit {IMPORTER_COMMIT}, got {commit}")
    if not (dependencies / "python" / "flatbuffers" / "__init__.py").is_file():
        raise FileNotFoundError("Install flatbuffers into the dependency cache; see the Switch README")
    executable = shutil.which(blender)
    if executable is None:
        raise FileNotFoundError(f"Blender executable not found: {blender}")
    return executable


def annotate_export(path: Path, *, species: int, name: str, asset_id: str,
                    expected_animations: set[str], source_game: str = "scarlet-violet") -> dict:
    glb = read_glb(path)
    doc = glb.json
    animations = doc.get("animations", [])
    actual = {clip.get("name") for clip in animations}
    if actual != expected_animations or len(animations) != len(expected_animations):
        raise ValueError(f"Exported animation names differ from source: {actual ^ expected_animations}")
    if not doc.get("skins") or not doc.get("meshes") or not doc.get("images"):
        raise ValueError("Export requires skinning, geometry and embedded textures")
    if any("uri" in image for image in doc["images"]):
        raise ValueError("GLB textures must be embedded")
    for mesh in doc["meshes"]:
        for primitive in mesh["primitives"]:
            if not {"JOINTS_0", "WEIGHTS_0"}.issubset(primitive["attributes"]):
                raise ValueError("A Pokémon mesh lost its skin weights")
    # glTF applies the skeleton's world transform to skinned meshes. Keep these
    # mesh nodes at scene root to avoid ambiguous parent transforms in consumers.
    skinned = {i for i, node in enumerate(doc["nodes"]) if "skin" in node}
    for i in skinned:
        if any(key in doc["nodes"][i] for key in ("matrix", "translation", "rotation", "scale")):
            raise ValueError("Expected identity skinned mesh transforms from Blender")
    scene_meshes = []
    for scene in doc["scenes"]:
        reachable, pending = set(), list(scene["nodes"])
        while pending:
            node = pending.pop()
            if node not in reachable:
                reachable.add(node)
                pending.extend(doc["nodes"][node].get("children", []))
        scene_meshes.append(reachable & skinned)
    for node in doc["nodes"]:
        if "children" in node:
            node["children"] = [i for i in node["children"] if i not in skinned]
            if not node["children"]:
                del node["children"]
    for scene, indices in zip(doc["scenes"], scene_meshes):
        scene["nodes"] = list(dict.fromkeys(scene["nodes"] + sorted(indices)))
    for material in doc.get("materials", []):
        material.setdefault("extras", {})["rae"] = {
            "platform": "switch", "schemaVersion": 1,
            "renderClass": {"BLEND":"blend","MASK":"mask"}.get(material.get("alphaMode"),"opaque"),
        }
    doc.setdefault("extras", {})["rae"] = {
        "platform": "switch", "schemaVersion": 1, "species": species,
        "name": name, "sourceAssetId": asset_id, "sourceGame": source_game,
        "importerCommit": IMPORTER_COMMIT,
        "materialPolicy": "baked-base-color",
        "rawOnly": ["tracm", "traef"],
    }
    glb.write(path)
    return {"file": path.name, "bytes": path.stat().st_size,
            "animations": len(animations), "skins": len(doc["skins"]),
            "meshes": len(doc["meshes"]), "materials": len(doc.get("materials", [])),
            "embeddedImages": len(doc["images"])}


def main() -> None:
    root = Path(__file__).resolve().parents[3]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("rom", type=Path)
    parser.add_argument("output", type=Path, help="New/empty local output directory")
    parser.add_argument("--asset-id", required=True, help="Internal ID, NOT the National Dex number")
    parser.add_argument("--species", required=True, type=int)
    parser.add_argument("--name", required=True)
    parser.add_argument("--dependencies", type=Path, default=root / ".cache/switch-tools")
    parser.add_argument("--blender", default=os.environ.get("RAE_BLENDER", "/Applications/Blender.app/Contents/MacOS/Blender"))
    args = parser.parse_args()
    if not re.fullmatch(r"[A-Za-z0-9_-]+", args.name):
        parser.error("--name must be a filename-safe species label")
    blender = check_dependencies(args.dependencies.resolve(), args.blender)
    output = args.output.resolve()
    extract_pokemon_bundle(args.rom.resolve(), output, args.asset_id, args.species, args.name)
    # File names follow Resort's National Dex convention; source asset IDs stay explicit.
    glb = output / f"pm{args.species:04}_00_{args.name}.glb"
    job = {"dependencies": str(args.dependencies.resolve()), "raw": str(output / "raw"),
           "output": str(output), "glb": str(glb), "assetId": args.asset_id,
           "species": args.species, "name": args.name}
    job_file = output / "job.json"
    job_file.write_text(json.dumps(job, indent=2) + "\n")
    worker = Path(__file__).with_name("blender_pokemon.py")
    with (output / "conversion.log").open("w") as log:
        subprocess.run([blender, "-b", "--factory-startup", "--python-exit-code", "1",
                        "--python", str(worker), "--", str(job_file)],
                       stdout=log, stderr=subprocess.STDOUT, check=True)
    clips = json.loads((output / "animation_manifest.json").read_text())["animations"]
    summary = annotate_export(glb, species=args.species, name=args.name, asset_id=args.asset_id,
                              expected_animations={clip["name"] for clip in clips})
    (output / "export_report.json").write_text(json.dumps(summary, indent=2) + "\n")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
