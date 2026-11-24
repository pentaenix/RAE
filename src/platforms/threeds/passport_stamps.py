"""Native USUM Trainer Passport PNG export, isolated to the 3DS module."""
from __future__ import annotations

import hashlib
import io
import json
from pathlib import Path

from PIL import Image

from .alyt import read_alyt_files
from .bflim import decode_bflim
from .container import ThreedsImage, parse_garc
from .game_catalog import is_ultra_moon_product_code
from .lz11 import maybe_decompress

PASSPORT_GARC = "/a/2/5/1"
TRIAL_NAMES = {
    "Mark_01": "melemele-trial-completion",
    "Mark_02": "akala-trial-completion",
    "Mark_03": "ulaula-trial-completion",
    "Mark_04": "poni-trial-completion",
    "Mark_05": "island-challenge-completion",
}


def export_passport_stamps(rom: str | Path, output: str | Path) -> dict:
    """Export the verified Ultra Moon archive, preserving native alpha/color.

    The Passport layout displays swizzle-8 stamp images with inverted texture Y.
    Correct that coordinate convention once on export, without filtering pixels.
    Other games and existing sprite-decoder behavior are deliberately untouched.
    """
    rom, output = Path(rom).resolve(), Path(output).resolve()
    for folder in ["png", "trials", "originals/bflim"]:
        (output / folder).mkdir(parents=True, exist_ok=True)
    with ThreedsImage(rom) as image:
        product = image.main_partition().product_code
        if not is_ultra_moon_product_code(product):
            raise ValueError("This Passport GARC profile is verified for Ultra Moon only")
        entry = next(f for f in image.romfs_files() if f.path == PASSPORT_GARC)
        slots = parse_garc(image, entry.offset)
        if len(slots) != 1:
            raise ValueError("Unexpected USUM Passport GARC layout")
        slot = slots[0]
        payload = maybe_decompress(image.read(slot.offset, slot.size))
    (output / "originals/trainer-pass.alyt").write_bytes(payload)
    records = []
    for item in read_alyt_files(payload):
        stem = Path(item.name).stem
        if not item.name.endswith(".bflim") or not (stem.startswith("Mark_") or stem.startswith("trainer_pass_stamp_")):
            continue
        texture = decode_bflim(item.data)
        png_image = Image.open(io.BytesIO(texture.to_png())).convert("RGBA")
        if texture.swizzle == 8:
            png_image = png_image.transpose(Image.Transpose.FLIP_TOP_BOTTOM)
        target = output / "png" / (stem + ".png")
        png_image.save(target)
        (output / "originals/bflim" / (stem + ".bflim")).write_bytes(item.data)
        record = {
            "source_name": item.name, "png": str(target.relative_to(output)),
            "dimensions": [texture.width, texture.height], "format": texture.format,
            "swizzle": texture.swizzle, "alpha_range": png_image.getchannel("A").getextrema(),
            "source_sha256": hashlib.sha256(item.data).hexdigest(),
            "png_sha256": hashlib.sha256(target.read_bytes()).hexdigest(),
            "orientation": "layout texture Y corrected" if texture.swizzle == 8 else "decoder orientation",
            "resampled": False,
        }
        if stem in TRIAL_NAMES:
            trial = output / "trials" / (TRIAL_NAMES[stem] + ".png")
            trial.write_bytes(target.read_bytes())
            record["trial_png"] = str(trial.relative_to(output))
        records.append(record)
    manifest = {
        "rom": rom.name, "product_code": product, "garc": PASSPORT_GARC,
        "slot": 0, "archive_sha256": hashlib.sha256(payload).hexdigest(),
        "decoder": "RAE threeds ALYT/SARC + BFLIM/PICA", "textures": records,
        "credit": "Original game artwork © Pokémon/Nintendo/Creatures/GAME FREAK",
    }
    (output / "texture-manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    return manifest
