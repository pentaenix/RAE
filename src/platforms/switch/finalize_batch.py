"""Recheck completed appearance passes and rebuild an authoritative batch report."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
from concurrent.futures import ThreadPoolExecutor

from .batch_gen9 import write_json
from .gltf.glb_io import read_glb


def finalize(directory: Path, entry: dict, validator: Path) -> dict:
    report_path=directory/"export_report.json"
    previous=json.loads(report_path.read_text()) if report_path.is_file() else {}
    path=directory/f"pm{entry['species']:04}_{entry['formNumber']:02}_{entry['label']}.glb"
    if not path.is_file():
        raise ValueError("Expected final GLB is absent")
    # Check original input assets again; appearance changes may only affect the
    # derived GLB, never silently authorize edits to a source bundle.
    raw=json.loads((directory/"raw_manifest.json").read_text())
    for file in raw["files"]:
        if hashlib.sha256((directory/"raw"/file["file"]).read_bytes()).hexdigest()!=file["sha256"]:
            raise ValueError("Original source bundle changed: "+file["file"])
    if entry.get('sourceFormat')=='gfbmdl':
        from .swsh_material_policy import apply_source_composite_policy
        apply_source_composite_policy(path,json.loads((directory/'job.json').read_text()))
    doc=read_glb(path).json
    clips=json.loads((directory/"animation_manifest.json").read_text())["animations"]
    if not doc.get("skins") or not doc.get("images") or not doc.get("meshes"):
        raise ValueError("Missing rig, textures or geometry")
    if {a["name"] for a in doc["animations"]}!={a["name"] for a in clips} or len(doc["animations"])!=len(clips):
        raise ValueError("Skeletal clip set changed")
    for mesh in doc["meshes"]:
        for primitive in mesh["primitives"]:
            if not {"JOINTS_0","WEIGHTS_0","TEXCOORD_0"}<=primitive["attributes"].keys():
                raise ValueError("Skinned primitive lost attributes")
    subprocess.run([shutil.which("node"),str(Path(__file__).with_name("validate_glb.js")),str(validator),
        str(path),str(directory/"gltf_validation.json")],check=True,capture_output=True,text=True)
    result={**previous,"file":path.name,"path":str(path),"bytes":path.stat().st_size,
        "sha256":hashlib.sha256(path.read_bytes()).hexdigest(),"animations":len(clips),
        "skins":len(doc["skins"]),"meshes":len(doc["meshes"]),"materials":len(doc["materials"]),
        "embeddedImages":len(doc["images"]),
        "shinyMaterials":sum("shinyMaterialIndex" in m.get("extras",{}).get("rae",{}) for m in doc["materials"]),
        "appearanceAxes":doc.get("extras",{}).get("rae",{}).get("appearanceVariants",{}).get("axes",[])}
    if entry.get("sourceFormat")=="gfbmdl":
        if doc.get("extras",{}).get("rae",{}).get("metersPerSourceUnit")!=.01:
            raise ValueError("Sword export has not been normalized to meters")
        result["appearancePipeline"]=2
        result["sourceScaleCompensation"]=True
    write_json(report_path,result)
    return {**entry,**result,"status":"complete","directory":str(directory)}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output",type=Path)
    parser.add_argument("--source-update")
    parser.add_argument("--workers",type=int,default=2)
    args=parser.parse_args()
    root=args.output.resolve()
    inventory=json.loads((root/"inventory.json").read_text())
    if args.source_update:inventory["sourceUpdate"]=args.source_update
    validator=Path(__file__).resolve().parents[3]/".cache/switch-tools/gltf-validator/node_modules/gltf-validator"
    def work(entry):
        directory=root/"forms"/entry["assetId"]
        try:
            result=finalize(directory,entry,validator)
        except Exception as exc:
            result={**entry,"status":"failed","error":str(exc),"directory":str(directory)}
        print(entry["assetId"],result["status"],result.get("error",""),flush=True)
        return result
    with ThreadPoolExecutor(max_workers=max(1,min(args.workers,4))) as pool:
        results=list(pool.map(work,inventory["forms"]))
    report={**inventory,"results":results,"completeForms":sum(e["status"]=="complete" for e in results),
            "failedForms":sum(e["status"]=="failed" for e in results)}
    write_json(root/"batch_report.json",report)
    write_json(root/"progress.json",{e["assetId"]:e for e in results})
    write_json(root/"inventory.json",inventory)
    print(f"Finalized: {report['completeForms']} complete, {report['failedForms']} failed",flush=True)


if __name__=="__main__":
    main()
