"""Resumable Gen 9-only extraction and animated conversion of local SV dumps."""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import threading
import time

from .gen9_catalog import GEN9_SPECIES, discover_gen9_forms, source_shiny_capabilities
from .pokemon_bundle import extract_pokemon_bundle
from .pokemon_export import annotate_export, check_dependencies
from .service import hash_cache_for_rom, iter_named_trinity_files, open_archive


def write_json(path: Path, value) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2) + "\n")
    temporary.replace(path)


def convert_form(entry: dict, rom: Path, output: Path, dependencies: Path,
                 blender: str, archive, cache, rows: list, *, validator: bool,
                 include_shiny: bool = False, extractor=None) -> dict:
    include_shiny = include_shiny and entry.get("shinyAvailable",True)
    directory = output / "forms" / entry["assetId"]
    directory.mkdir(parents=True, exist_ok=True)
    final = directory / f"pm{entry['species']:04}_{entry['formNumber']:02}_{entry['label']}.glb"
    report_path = directory / "export_report.json"
    if report_path.is_file() and final.is_file():
        report = json.loads(report_path.read_text())
        current = entry.get("sourceFormat") != "gfbmdl" or report.get("appearancePipeline") == 2
        current = current and (not entry.get("sourceScaleCompensation") or report.get("sourceScaleCompensation"))
        if current and report.get("sha256") == hashlib.sha256(final.read_bytes()).hexdigest() and (not include_shiny or report.get("shinyMaterials")):
            return {**entry, "status": "complete", "directory": str(directory), **report}
    raw_manifest = directory / "raw_manifest.json"
    if not raw_manifest.is_file():
        if any(directory.iterdir()):
            raise RuntimeError(f"Partial raw extraction needs review: {directory}")
        if extractor is not None:
            extractor(entry, directory)
        else:
            extract_pokemon_bundle(rom, directory, entry["assetId"], entry["species"],
                               entry["name"], lambda _: None, archive=archive, cache=cache,
                               indexed_rows=rows, allow_regional_forms=entry["species"] < 808)
    else:
        manifest = json.loads(raw_manifest.read_text())
        if manifest["assetId"] != entry["assetId"] or manifest["species"] != entry["species"]:
            raise RuntimeError("Raw bundle identity does not match this form")
        for file in manifest["files"]:
            source = directory / "raw" / file["file"]
            if not source.is_file() or hashlib.sha256(source.read_bytes()).hexdigest() != file["sha256"]:
                raise RuntimeError(f"Raw source changed or missing: {source}")
    job = {**entry, "dependencies": str(dependencies), "raw": str(directory / "raw"),
           "output": str(directory), "glb": str(final), "includeShiny": include_shiny}
    write_json(directory / "job.json", job)
    with (directory / "conversion.log").open("w") as log:
        subprocess.run([blender, "-b", "--factory-startup", "-t", "2", "--python-exit-code", "1",
                        "--python", str(Path(__file__).with_name("blender_pokemon.py")),
                        "--", str(directory / "job.json")],
                       stdout=log, stderr=subprocess.STDOUT, check=True, timeout=2400)
    animations = json.loads((directory / "animation_manifest.json").read_text())["animations"]
    summary = annotate_export(final, species=entry["species"], name=entry["name"],
                              asset_id=entry["assetId"],
                              expected_animations={clip["name"] for clip in animations},
                              source_game="sword-shield" if entry.get("sourceFormat") == "gfbmdl" else "scarlet-violet")
    summary["sourceScaleCompensation"] = job.get("sourceScaleCompensation",entry.get("sourceFormat")=="gfbmdl")
    if include_shiny:
        from .appearance_glb import add_shiny_variant
        summary.update(add_shiny_variant(final, directory / "shiny.glb"))
    if entry.get("sourceFormat") == "gfbmdl":
        from .glb_units import centimeters_to_meters
        centimeters_to_meters(final)
        summary["appearancePipeline"] = 2
    if validator:
        package = dependencies / "gltf-validator/node_modules/gltf-validator"
        subprocess.run([shutil.which("node") or "node", str(Path(__file__).with_name("validate_glb.js")),
                        str(package), str(final), str(directory / "gltf_validation.json")],
                       check=True, capture_output=True, text=True)
    summary["sha256"] = hashlib.sha256(final.read_bytes()).hexdigest()
    summary["path"] = str(final)
    write_json(report_path, summary)
    return {**entry, "status": "complete", "directory": str(directory), **summary}


def main() -> None:
    root = Path(__file__).resolve().parents[3]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("rom", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--workers", type=int, default=3)
    parser.add_argument("--blender", default="/Applications/Blender.app/Contents/MacOS/Blender")
    parser.add_argument("--dependencies", type=Path, default=root / ".cache/switch-tools")
    parser.add_argument("--inventory-only", action="store_true")
    parser.add_argument("--update", type=Path)
    parser.add_argument("--include-shiny", action="store_true")
    parser.add_argument("--catalog", type=Path, help="Explicit additional physical forms, preserving their source identity")
    parser.add_argument("--global-joint-poses",action="store_true",help="Export evaluated world poses under a common identity skeleton root")
    parser.add_argument("--only", type=int, nargs="*", help="Optional National Dex subset for repair")
    args = parser.parse_args()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    rom = args.rom.resolve()
    dependencies = args.dependencies.resolve()
    archive = open_archive(rom, update_path=args.update)
    cache = hash_cache_for_rom(rom)
    entries = source_shiny_capabilities(archive,json.loads(args.catalog.read_text())) if args.catalog else discover_gen9_forms(archive)
    if args.global_joint_poses:
        for entry in entries:
            if not args.only or entry["species"] in args.only:
                entry["sourceScaleCompensation"]=True
    present = {entry["species"] for entry in entries}
    missing = [] if args.catalog else [dict(value, status="not_in_dump") for dex, value in GEN9_SPECIES.items() if dex not in present]
    inventory = {"sourceRom": rom.name, "generation": 9, "speciesRange": [906, 1025],
                 "sourceUpdate": args.update.name if args.update else None,
                 "sourceAttachments": [] if args.catalog else [entry for entry in discover_gen9_forms(archive,include_attachments=True) if entry["assetKind"]=="attachment"],
                 "forms": entries, "missingSpecies": missing,
                 "availableSpecies": len(present), "availableForms": len(entries)}
    write_json(output / "inventory.json", inventory)
    print(f"Inventory: {len(present)}/120 Gen 9 species, {len(entries)} forms; {len(missing)} species absent", flush=True)
    if args.inventory_only:
        return
    blender = check_dependencies(dependencies, args.blender)
    # Build the index once instead of reparsing the ROM/hash list for each form.
    by_form = {entry["assetId"]: [] for entry in entries}
    for row in iter_named_trinity_files(archive, cache, contains="pokemon/data/"):
        parts = row[1].split("/")
        if len(parts) > 3 and parts[3] in by_form:
            by_form[parts[3]].append(row)
    if args.only:
        entries = [entry for entry in entries if entry["species"] in args.only]
    progress_path = output / "progress.json"
    previous = json.loads(progress_path.read_text()) if progress_path.is_file() else {}
    states = {entry["assetId"]: previous.get(entry["assetId"], dict(entry, status="pending")) for entry in inventory["forms"]}
    lock = threading.Lock()

    def work(entry):
        asset = entry["assetId"]
        with lock:
            states[asset] = dict(entry, status="running", startedAt=time.time())
            write_json(progress_path, states)
        try:
            result = convert_form(entry, rom, output, dependencies, blender, archive, cache,
                                  by_form[asset], validator=True, include_shiny=args.include_shiny)
        except Exception as exc:
            result = dict(entry, status="failed", error=str(exc),
                          directory=str(output / "forms" / asset))
        with lock:
            states[asset] = result
            write_json(progress_path, states)
            counts = {key: sum(value["status"] == key for value in states.values())
                      for key in ("complete", "failed", "running", "pending")}
            print(f"{entry['species']} {entry['name']} {asset}: {result['status']} | {counts}", flush=True)
        return result

    with ThreadPoolExecutor(max_workers=max(1, min(args.workers, 4))) as pool:
        futures = [pool.submit(work, entry) for entry in entries]
        for future in as_completed(futures):
            future.result()
    report = {**inventory, "results": list(states.values()),
              "completeForms": sum(value["status"] == "complete" for value in states.values()),
              "failedForms": sum(value["status"] == "failed" for value in states.values())}
    write_json(output / "batch_report.json", report)
    print(f"Batch finished: {report['completeForms']} complete, {report['failedForms']} failed", flush=True)


if __name__ == "__main__":
    main()
