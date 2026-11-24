#!/usr/bin/env python3
"""Export the Black 2 ship/ocean sets used by Pokemon Resort's start scene."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from rae.platforms.nds.model_module.preview_pipeline import export_textured_model_glb
from rae.platforms.nds.rom import NDSRom
from rae.platforms.nds.scanner import scan_blob


EXPORTS = (
    ("a/1/5/8", "vessels", "virbank_deck", 59, (60,)),
    # 0464 is the Liberty Garden arrival/parking skeleton. The opening scene
    # needs the stationary travel hull with only its wake material motion.
    ("a/1/5/8", "vessels", "liberty_yellow", 465, (466,)),
    # The port cutscene's 0041/0042/0043 set animates the Royal Unova parking.
    # The field-scene set below is the cruising hull plus its 1,200-frame wake.
    ("a/1/4/8", "vessels", "royal_unova", 16, (17,)),
    # The BCA clips bob the complete ship/wake assembly. The game owns the
    # hull's vertical-only bob so the BTA can scroll each wake independently.
    ("a/1/5/8", "vessels", "virbank_forward", 439, (440,)),
    ("a/1/5/8", "vessels", "virbank_side", 443, (444,)),
    # The BCA clips move the entire cutscene set past its original camera. The
    # start scene owns its camera, so keep only the BTA material motion that
    # scrolls the ocean textures in place.
    ("a/1/5/8", "environments", "ocean_day", 401, (402,)),
    ("a/1/5/8", "environments", "ocean_sunset", 404, (405,)),
    ("a/1/5/8", "environments", "ocean_night", 407, (408,)),
    ("a/1/5/8", "skies", "day_dome_0409", 409, ()),
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("rom", type=Path, help="Pokemon Black 2 .nds path")
    parser.add_argument("output", type=Path, help="Destination asset directory")
    parser.add_argument("--only", choices=[entry[2] for entry in EXPORTS], help="Export one asset without replacing the others")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    exports = [entry for entry in EXPORTS if not args.only or entry[2] == args.only]
    rom = NDSRom.from_path(str(args.rom))
    rom_files = {item.path: item for item in rom.iter_files()}
    assets_by_archive = {}
    for archive_path in sorted({entry[0] for entry in exports}):
        archive = rom_files.get(archive_path)
        if archive is None:
            raise RuntimeError(f"ROM does not contain {archive_path}")
        by_index = {}
        for asset in scan_blob(
            archive_path,
            archive.data,
            rom_file_id=archive.file_id,
            rom_offset=archive.start,
            carve_unknown_blobs=False,
        ):
            stem = Path(asset.virtual_path).name.split(".", 1)[0]
            if stem.startswith("file_"):
                by_index[int(stem.removeprefix("file_"))] = asset
        assets_by_archive[archive_path] = by_index

    manifest = {
        "sourceArchives": sorted(assets_by_archive),
        "assets": {},
    }
    manifest_path = args.output / "rae_sources.json"
    if args.only and manifest_path.is_file():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["sourceArchives"] = sorted(set(manifest.get("sourceArchives", [])) | set(assets_by_archive))
    for archive_path, category, asset_id, model_index, animation_indices in exports:
        by_index = assets_by_archive[archive_path]
        model = by_index[model_index]
        group = [model, *(by_index[index] for index in animation_indices)]
        relative = Path(category) / f"{asset_id}.glb"
        destination = args.output / relative.parent
        print(
            f"Exporting {asset_id} from {archive_path}: "
            f"model {model_index}, animations {animation_indices}"
        )
        export_textured_model_glb(
            model,
            group,
            destination,
            glb_filename=relative.name,
            progress=lambda message, prefix=asset_id: print(f"[{prefix}] {message}"),
        )
        manifest["assets"][asset_id] = {
            "path": relative.as_posix(),
            "model": f"{archive_path}/file_{model_index:04d}.bin.nsbmd",
            "animations": [f"{archive_path}/file_{index:04d}.bin" for index in animation_indices],
        }

    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / "rae_sources.json").write_text(
        json.dumps(manifest, indent=2) + "\n",
        encoding="utf-8",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
