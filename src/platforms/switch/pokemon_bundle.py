"""Extract one exact Trinity Pokémon form without mixing model providers."""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path, PurePosixPath

from .bntx import decode_bntx, UnsupportedTextureError
from .service import hash_cache_for_rom, iter_named_trinity_files, open_archive
from .fnv import fnv1a64


def bundle_relative_path(inner: str, prefix: str) -> Path:
    path = PurePosixPath(inner)
    relative = path.relative_to(PurePosixPath(prefix))
    if not relative.parts or any(p in ("..", ".") for p in relative.parts) or "\\" in inner:
        raise ValueError(f"Unsafe archive path: {inner}")
    return Path(*relative.parts)


def extract_pokemon_bundle(rom: Path, output: Path, asset_id: str, species: int,
                           name: str, progress=print, *, archive=None, cache=None,
                           indexed_rows=None, allow_regional_forms: bool = False) -> dict:
    if not re.fullmatch(r"pm\d{4}_\d{2}_\d{2}", asset_id):
        raise ValueError("Asset ID must be an internal form ID such as pm1010_00_00")
    if not 1 <= species <= 1025:
        raise ValueError("Species must be a Gen 1–9 National Dex identity")
    newer_form = asset_id[-2:] in ("41", "51") or asset_id in ("pm0483_12_00","pm0484_12_00")
    if species < 810 and not (allow_regional_forms and newer_form):
        raise ValueError("Gen 8/9 species only unless a newer regional form is explicitly requested")
    prefix = f"pokemon/data/{asset_id[:6]}/{asset_id}/"
    archive = archive or open_archive(rom, progress)
    cache = cache or hash_cache_for_rom(rom, progress)
    rows = list(indexed_rows) if indexed_rows is not None else list(
        iter_named_trinity_files(archive, cache, contains=prefix))
    rows = [row for row in rows if row[1].startswith(prefix)]
    # Some published hash-list entries alias a normal model as its rare model.
    # The real default model's path hash is authoritative for the ROM we opened.
    model_path = prefix + asset_id + ".trmdl"
    if not any(row[1] == model_path for row in rows):
        pack = archive.resolve_trpak_path(model_path, file_hash=fnv1a64(model_path))
        rows.append((pack, model_path, fnv1a64(model_path)))
    if not any(row[1] == prefix + asset_id + ".trmdl" for row in rows):
        raise FileNotFoundError(f"Model {asset_id} is not present in this ROM/hash index")
    if output.exists() and any(output.iterdir()):
        raise FileExistsError(f"Use an empty output directory: {output}")
    raw = output / "raw"
    raw.mkdir(parents=True, exist_ok=True)
    files = []
    textures = []
    undecoded = []
    for i, (pack, inner, file_hash) in enumerate(rows):
        relative = bundle_relative_path(inner, prefix)
        payload = archive.read_by_path(
            archive.resolve_trpak_path(inner, pack, file_hash=file_hash), inner)
        destination = raw / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(payload)
        files.append({"path": inner, "file": relative.as_posix(), "bytes": len(payload),
                      "sha256": hashlib.sha256(payload).hexdigest()})
        if destination.suffix == ".bntx":
            from PIL import Image

            try:
                decoded = decode_bntx(payload)
            except UnsupportedTextureError as exc:
                undecoded.append({"file":relative.as_posix(),"reason":str(exc)})
                decoded = []
            for texture in decoded:
                if Path(texture.name).name != texture.name or "\\" in texture.name:
                    raise ValueError("Unsafe embedded BNTX texture name")
                png = destination.parent / (texture.name + ".png")
                Image.frombytes("RGBA", (texture.width, texture.height), texture.rgba).save(png)
                textures.append({"file": str(png.relative_to(raw)), "width": texture.width,
                                 "height": texture.height, "format": texture.format})
        if i % 25 == 0:
            progress(f"Switch: extracted {i + 1}/{len(rows)} form assets")
    manifest = {"schemaVersion": 1, "species": species, "name": name, "assetId": asset_id,
                "sourceRom": rom.name, "sourceUpdate": getattr(archive,"source_update",None),
                "files": files, "textures": textures, "undecodedTextures":undecoded}
    (output / "raw_manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    return manifest
