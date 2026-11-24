"""Internal model identities for additive Gen 8/9 and newer regional forms.

Model ID reference: https://archive.vg-resource.com/thread-25872.html (RTB).
Names are stored as local data so no other platform's species module is imported.
"""
from __future__ import annotations

import json
from pathlib import Path
import re

from .gen9_catalog import MODEL_TO_DEX, file_label

_SWSH_DEX = (
    827,828,833,834,829,830,835,836,819,820,831,832,846,847,850,851,845,821,822,823,
    848,849,870,868,869,878,879,862,884,824,825,826,837,838,839,843,844,888,889,890,
    877,876,863,871,872,873,864,810,811,812,816,817,818,813,814,815,859,860,861,880,
    881,882,883,852,853,840,841,842,856,857,858,854,855,874,875,885,886,887,867,866,
    865,891,892,896,897,898,893,894,895,
)
ALL_MODEL_TO_DEX = {**dict(zip((*range(901,987),988,989,990), _SWSH_DEX, strict=True)),
                    891:808, 892:809, **MODEL_TO_DEX,
                    **dict(zip(range(1001,1008), (899,900,903,905,904,902,901), strict=True))}
# Old models needed for newer regional forms; pre-Kalos model IDs match the Dex.
REGIONAL_MODEL_TO_DEX = {**{i:i for i in range(1,650)}, 751:713,764:705,765:706,843:724}
NAMES = {int(k): v for k,v in json.loads(Path(__file__).with_name("species_names.json").read_text()).items()}


def describe_assets(assets: list[str], *, source: str) -> list[dict]:
    by_species = {}
    for asset in sorted(set(assets)):
        model = int(asset[2:6])
        dex = ALL_MODEL_TO_DEX.get(model)
        segments = asset.split("_")[1:]
        if dex is None:
            # These generations introduced regional and Gigantamax models absent
            # from the preferred Gen 7 provider. Ordinary old models stay there.
            regional = source == "sv" and segments[-1] in ("41", "51")
            regional |= source == "sv" and model in (483,484) and segments[0] == "12"
            regional |= source == "swsh" and (segments[-1] == "31" or segments[0] in ("81", "82"))
            regional |= source == "swsh" and model == 25 and segments == ["25"]
            if not regional:
                continue
            dex = REGIONAL_MODEL_TO_DEX.get(model)
        if dex is not None:
            by_species.setdefault(dex, []).append(asset)
    result = []
    for dex, forms in sorted(by_species.items()):
        forms.sort(key=lambda a: (not (a.endswith("_00_00") or a.endswith("_00")), a))
        for index, asset in enumerate(forms):
            # An older species' new physical forms must have distinct IDs from
            # its existing Gen 7 model and from the other provider's forms.
            number = index if dex >= 808 else index + (100 if source == "swsh" else 200)
            suffix = "" if index == 0 and dex >= 808 else "_Form" + asset[7:]
            result.append({"species":dex,"name":NAMES[dex],"assetId":asset,
                "formNumber":number,"label":file_label(NAMES[dex])+suffix,
                "sourceFormat":"gfbmdl" if source == "swsh" else "trmdl",
                "modelFile":asset+(".gfbmdl" if source == "swsh" else ".trmdl")})
    return result


def discover_swsh_forms(files) -> list[dict]:
    assets = [Path(f.path).stem for f in files
              if re.fullmatch(r"/bin/archive/pokemon/pm\d{4}_\d{2}(?:_\d{2})?\.gfpak", f.path)]
    return describe_assets(assets, source="swsh")
