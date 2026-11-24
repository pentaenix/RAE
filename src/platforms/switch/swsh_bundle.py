"""Extract exact Sword/Shield form packs with normal/rare source models."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re

from .bntx import decode_bntx, UnsupportedTextureError
from .fnv import fnv1a64
from .gfpak import read_gfpak


def extract_swsh_bundle(rom, entry, output: Path, *, species: int, name: str) -> dict:
    if output.exists() and any(output.iterdir()):
        raise FileExistsError(f"Use an empty output directory: {output}")
    asset = Path(entry.path).stem
    if not re.fullmatch(r"pm\d{4}_\d{2}(?:_\d{2})?", asset):
        raise ValueError("Unexpected Sword/Shield pack identity")
    data = rom.read_file(entry)
    files = read_gfpak(data)
    candidates = {asset + ".gfbmdl", asset + "_rare.gfbmdl"}
    for file in files:
        candidates.update(s.decode() for s in re.findall(rb"[A-Za-z0-9_-]+\.(?:gfbanm|gfbmdl|gfbmot|gfbpokecfg)", file.data))
    names = {fnv1a64(n): n for n in candidates}
    raw = output / "raw"
    raw.mkdir(parents=True)
    manifest, textures, undecoded = [], [], []
    for file in files:
        filename = names.get(file.name_hash, f"{file.index:04}_{file.name_hash:016x}.bin")
        destination = raw / filename
        destination.write_bytes(file.data)
        manifest.append({"file": filename, "nameHash": f"{file.name_hash:016x}",
                         "absoluteHash": f"{file.absolute_hash:016x}", "bytes": len(file.data),
                         "sha256": hashlib.sha256(file.data).hexdigest()})
        if file.data[:4] == b"BNTX":
            from PIL import Image
            try:
                decoded = decode_bntx(file.data)
            except UnsupportedTextureError as exc:
                undecoded.append({"file":filename,"reason":str(exc)})
                decoded = []
            for texture in decoded:
                if Path(texture.name).name != texture.name or "\\" in texture.name:
                    raise ValueError("Unsafe embedded texture name")
                png = raw / (texture.name + ".png")
                Image.frombytes("RGBA", (texture.width, texture.height), texture.rgba).save(png)
                textures.append({"file": png.name, "width": texture.width, "height": texture.height})
    for filename in (asset + ".gfbmdl", asset + "_rare.gfbmdl"):
        if not (raw / filename).is_file():
            raise ValueError(f"Source normal/rare model missing: {filename}")
    result = {"schemaVersion": 1, "sourceRom": rom.base.path.name, "sourceUpdate": rom.patch.path.name,
              "sourcePack": entry.path, "packSha256": hashlib.sha256(data).hexdigest(),
              "assetId": asset, "species": species, "name": name,
              "files": manifest, "textures": textures,"undecodedTextures":undecoded}
    (output / "raw_manifest.json").write_text(json.dumps(result, indent=2) + "\n")
    return result
