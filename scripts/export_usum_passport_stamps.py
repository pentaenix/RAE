"""Export native transparent Ultra Moon Passport stamps with RAE."""
import argparse
from rae.platforms.threeds.passport_stamps import export_passport_stamps

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("rom")
parser.add_argument("--out", required=True)
args = parser.parse_args()
manifest = export_passport_stamps(args.rom, args.out)
print(f"Exported {len(manifest['textures'])} native PNGs, including four trial stamps and Island Challenge completion.")
