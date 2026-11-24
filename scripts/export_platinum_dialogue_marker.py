#!/usr/bin/env python3
"""Extract Platinum's original three-frame scroll cursor using RAE decoders."""
import argparse
from pathlib import Path
from zipfile import ZipFile

from PIL import Image
from rae.platforms.nds.rom import NDSRom
from rae.platforms.nds.narc import NarcArchive
from rae.platforms.nds.nitro_2d import parse_ncgr, decode_nclr_colors, tile_pixels


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("rom", type=Path, help="Platinum .nds or ZIP containing it")
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    if args.rom.suffix.lower() == ".zip":
        with ZipFile(args.rom) as archive:
            names = [n for n in archive.namelist() if n.lower().endswith(".nds")]
            if len(names) != 1:
                raise ValueError("Expected exactly one .nds in ZIP")
            rom = NDSRom(archive.read(names[0]))
    else:
        rom = NDSRom.from_path(str(args.rom))
    if not rom.info.game_code.startswith("CPU"):
        raise ValueError("Expected Pokemon Platinum ROM")
    member = next(f for f in rom.iter_files() if f.path == "graphic/pl_winframe.narc")
    entries = list(NarcArchive(member.data).iter_files())
    # Platinum pl_winframe.order: scroll_cursor NCGR=22, message_box_00 NCLR=25.
    gfx = parse_ncgr(entries[22].data)
    palette = decode_nclr_colors(entries[25].data)
    if not gfx or gfx.tile_count != 12 or len(palette) < 16:
        raise ValueError("Unexpected scroll cursor geometry/palette")
    source = Image.new("RGBA", (16, 48))
    for tile in range(12):
        image = Image.new("RGBA", (8, 8))
        image.putdata(tile_pixels(gfx, tile, palette))
        source.paste(image, ((tile % 2)*8, (tile//2)*8))
    sheet = Image.new("RGBA", (36, 16))
    for frame in range(3):
        sheet.paste(source.crop((4, frame*16, 16, (frame+1)*16)), (frame*12, 0))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(args.output)
    print(f"Exported {args.output}: 3 original 12x16 frames, transparent palette index 0")


if __name__ == "__main__":
    main()
