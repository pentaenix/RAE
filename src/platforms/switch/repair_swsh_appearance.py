"""Rebake Sword materials with their original UV transforms and alpha."""
from concurrent.futures import ThreadPoolExecutor,as_completed
import argparse
import hashlib
import json
from pathlib import Path
import subprocess

from .appearance_glb import add_shiny_variant,replace_base_materials
from .compact_glb import compact_appearances
from .glb_units import centimeters_to_meters
from .swsh_material_policy import apply_source_composite_policy


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output",type=Path)
    parser.add_argument("--workers",type=int,default=2)
    parser.add_argument("--only",nargs="*")
    args=parser.parse_args()
    root=args.output.resolve()
    selected=[]
    for directory in sorted((root/"forms").iterdir()):
        if args.only and directory.name not in args.only:continue
        jobfile=directory/"job.json"
        if not jobfile.is_file() or not (directory/"animation_manifest.json").is_file():continue
        job=json.loads(jobfile.read_text())
        if not Path(job["glb"]).is_file():continue
        selected.append((directory,job))
    def work(item):
        directory,job=item
        stamp=directory/"appearance_repair.json"
        previous=json.loads(stamp.read_text()) if stamp.exists() else {}
        target=Path(job["glb"])
        if previous.get("version")==3 and previous.get("sha256")==hashlib.sha256(target.read_bytes()).hexdigest():
            if previous.get('compositePolicy')!=1:
                changes=apply_source_composite_policy(target,job)
                previous.update(compositePolicy=1,compositeMaterials=changes,sha256=hashlib.sha256(target.read_bytes()).hexdigest())
                stamp.write_text(json.dumps(previous,indent=2)+'\n')
                if changes:print('Source composite repaired:',directory.name,flush=True)
            return
        normal,rare=[directory/f"appearance_uv3_{color}.glb" for color in ("normal","rare")]
        if not all(p.is_file() for p in (normal,rare)):
            appearance_job=directory/'appearance_uv3_job.json'
            appearance_job.write_text(json.dumps({**job,'appearancePrefix':'appearance_uv3'},indent=2)+'\n')
            with (directory/"appearance_uv3_repair.log").open("w") as log:
                subprocess.run(["/Applications/Blender.app/Contents/MacOS/Blender","-b","--factory-startup","-t","2",
                    "--python-exit-code","1","--python",str(Path(__file__).with_name("blender_swsh_appearance.py")),
                    "--",str(appearance_job)],stdout=log,stderr=subprocess.STDOUT,check=True,timeout=1200)
        from .gltf.glb_io import read_glb
        for source in (normal,rare):
            if not read_glb(source).json.get("extras",{}).get("rae",{}).get("metersPerSourceUnit"):
                centimeters_to_meters(source)
        original=target.read_bytes()
        try:
            replace_base_materials(target,normal)
            add_shiny_variant(target,rare)
            compact_appearances(target)
            changes=apply_source_composite_policy(target,job)
        except Exception:
            target.write_bytes(original)
            raise
        stamp.write_text(json.dumps({"version":3,'compositePolicy':1,'compositeMaterials':changes,"sha256":hashlib.sha256(target.read_bytes()).hexdigest()},indent=2)+"\n")
        print("Source materials repaired:",directory.name,flush=True)
    print(f"Appearance pass: {len(selected)} models",flush=True)
    failures=[]
    with ThreadPoolExecutor(max_workers=max(1,min(args.workers,3))) as pool:
        pending={pool.submit(work,item):item[0].name for item in selected}
        for future in as_completed(pending):
            try:future.result()
            except Exception as exc:
                failures.append(pending[future]);print('Material repair failed:',pending[future],str(exc),flush=True)
    if failures:raise RuntimeError('Material repair failed for: '+', '.join(failures))


if __name__=="__main__":main()
