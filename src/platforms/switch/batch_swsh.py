"""Resumable additive Sword/Shield normal/shiny and animation extraction."""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import json
from pathlib import Path
import threading

from .batch_gen9 import convert_form, write_json
from .complete_catalog import discover_swsh_forms
from .patch_romfs import PatchedSwitchRom
from .pokemon_export import check_dependencies
from .swsh_bundle import extract_swsh_bundle


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("rom", type=Path)
    parser.add_argument("update", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--workers", type=int, default=2)
    parser.add_argument("--only", type=int, nargs="*")
    parser.add_argument("--inventory-only", action="store_true")
    args = parser.parse_args()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    dependencies = Path(__file__).resolve().parents[3] / ".cache/switch-tools"
    blender = check_dependencies(dependencies, "/Applications/Blender.app/Contents/MacOS/Blender")
    with PatchedSwitchRom(args.rom, args.update) as rom:
        files = {Path(f.path).stem:f for f in rom.romfs_files() if "/archive/pokemon/" in f.path}
        entries = discover_swsh_forms(files.values())
        inventory = {"sourceRom":args.rom.name,"sourceUpdate":args.update.name,
                     "forms":entries,"missingSpecies":[],"availableForms":len(entries),
                     "availableSpecies":len({e["species"] for e in entries})}
        write_json(output/"inventory.json",inventory)
        print(f"Sword inventory: {inventory['availableSpecies']} species, {len(entries)} forms",flush=True)
        if args.inventory_only:
            return
        progress = output/"progress.json"
        previous = json.loads(progress.read_text()) if progress.is_file() else {}
        states = {e["assetId"]:previous.get(e["assetId"],dict(e,status="pending")) for e in entries}
        lock = threading.Lock()
        extraction_lock = threading.Lock()

        def extract(entry,directory):
            with extraction_lock:
                extract_swsh_bundle(rom,files[entry["assetId"]],directory,
                                    species=entry["species"],name=entry["name"])

        def work(entry):
            with lock:
                states[entry["assetId"]] = dict(entry,status="running")
                write_json(progress,states)
            try:
                result = convert_form(entry,args.rom,output,dependencies,blender,None,None,[],
                                      validator=True,include_shiny=True,extractor=extract)
            except Exception as exc:
                result = dict(entry,status="failed",error=str(exc),directory=str(output/"forms"/entry["assetId"]))
            with lock:
                states[entry["assetId"]] = result
                write_json(progress,states)
                counts = {s:sum(v["status"]==s for v in states.values()) for s in ("complete","failed","running","pending")}
                print(f"{entry['species']} {entry['assetId']}: {result['status']} | {counts}",flush=True)

        selected = [e for e in entries if not args.only or e["species"] in args.only]
        with ThreadPoolExecutor(max_workers=max(1,min(args.workers,4))) as pool:
            for future in as_completed([pool.submit(work,e) for e in selected]):
                future.result()
        write_json(output/"batch_report.json",{**inventory,"results":list(states.values()),
            "completeForms":sum(v["status"]=="complete" for v in states.values()),
            "failedForms":sum(v["status"]=="failed" for v in states.values())})


if __name__ == "__main__":
    main()
