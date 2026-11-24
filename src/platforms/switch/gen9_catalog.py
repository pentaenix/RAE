"""National Dex identities for Gen 9 only, independent of internal model IDs.

Internal IDs: Random Talking Bush's published model ID table:
https://archive.vg-resource.com/thread-25872.html (post 1, Gen 9 model IDs).
Hisui's pm1001–1007 models belong to Gen 8 and are intentionally excluded.
"""
from __future__ import annotations

import re

from .fnv import fnv1a64

_NAMES = (
    "Sprigatito|Floragato|Meowscarada|Fuecoco|Crocalor|Skeledirge|Quaxly|Quaxwell|Quaquaval|"
    "Lechonk|Oinkologne|Tarountula|Spidops|Nymble|Lokix|Pawmi|Pawmo|Pawmot|Tandemaus|Maushold|"
    "Fidough|Dachsbun|Smoliv|Dolliv|Arboliva|Squawkabilly|Nacli|Naclstack|Garganacl|Charcadet|"
    "Armarouge|Ceruledge|Tadbulb|Bellibolt|Wattrel|Kilowattrel|Maschiff|Mabosstiff|Shroodle|Grafaiai|"
    "Bramblin|Brambleghast|Toedscool|Toedscruel|Klawf|Capsakid|Scovillain|Rellor|Rabsca|Flittle|"
    "Espathra|Tinkatink|Tinkatuff|Tinkaton|Wiglett|Wugtrio|Bombirdier|Finizen|Palafin|Varoom|"
    "Revavroom|Cyclizar|Orthworm|Glimmet|Glimmora|Greavard|Houndstone|Flamigo|Cetoddle|Cetitan|"
    "Veluza|Dondozo|Tatsugiri|Annihilape|Clodsire|Farigiraf|Dudunsparce|Kingambit|Great Tusk|Scream Tail|"
    "Brute Bonnet|Flutter Mane|Slither Wing|Sandy Shocks|Iron Treads|Iron Bundle|Iron Hands|Iron Jugulis|Iron Moth|Iron Thorns|"
    "Frigibax|Arctibax|Baxcalibur|Gimmighoul|Gholdengo|Wo-Chien|Chien-Pao|Ting-Lu|Chi-Yu|Roaring Moon|"
    "Iron Valiant|Koraidon|Miraidon|Walking Wake|Iron Leaves|Dipplin|Poltchageist|Sinistcha|Okidogi|Munkidori|"
    "Fezandipiti|Ogerpon|Archaludon|Hydrapple|Gouging Fire|Raging Bolt|Iron Boulder|Iron Crown|Terapagos|Pecharunt"
).split("|")

# In internal-model order: pm1010..1114, then pm1120..1134.
_DEX_ORDER = (
    906,907,908,909,910,911,912,913,914,915,916,982,917,918,919,920,953,954,971,972,
    955,956,981,960,961,977,976,963,964,928,929,930,951,952,938,939,965,966,968,924,
    925,974,975,996,997,998,978,967,921,922,923,940,941,962,931,973,950,932,933,934,
    969,970,944,945,926,927,942,943,946,947,999,1000,984,986,1009,989,985,987,988,1005,
    990,1010,994,992,993,995,991,1006,1003,1002,1001,1004,1007,1008,957,958,959,935,936,937,
    948,949,983,980,979,
    1017,1011,1019,1014,1015,1016,1020,1021,1023,1022,1024,1025,1018,1012,1013,
)
GEN9_SPECIES = {dex: {"species": dex, "name": name} for dex, name in enumerate(_NAMES, 906)}
MODEL_TO_DEX = dict(zip((*range(1010, 1115), *range(1120, 1135)), _DEX_ORDER, strict=True))


def file_label(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9_-]", "_", name)


def discover_gen9_forms(archive, *, include_attachments=False) -> list[dict]:
    """Use the ROM's real path hashes, not possibly stale hash-list aliases."""
    forms = set()
    for pack in archive._trpfd.trpak_paths:
        match = re.search(r"pokemondata(pm\d{4})(pm\d{4}_\d{2}_\d{2})", pack)
        if match and int(match[1][2:]) in MODEL_TO_DEX and archive.trpak_in_trpfs(pack):
            forms.add(match[2])
    entries = []
    by_species: dict[int, list[str]] = {}
    for asset in sorted(forms):
        dex = MODEL_TO_DEX[int(asset[2:6])]
        inner = f"pokemon/data/{asset[:6]}/{asset}/{asset}.trmdl"
        try:
            archive.resolve_trpak_path(inner, file_hash=fnv1a64(inner))
        except Exception:
            continue
        by_species.setdefault(dex, []).append(asset)
    for dex, assets in sorted(by_species.items()):
        assets.sort(key=lambda value: (not value.endswith("_00_00"), value))
        for index, asset in enumerate(assets):
            name = GEN9_SPECIES[dex]["name"]
            suffix = "" if index == 0 else f"_Form{asset[7:]}"
            entries.append({"species": dex, "name": name, "assetId": asset,
                            "formNumber": index, "label": file_label(name) + suffix,
                            "modelFile": asset + ".trmdl"})
    for entry in entries:
        entry["assetKind"] = "attachment" if entry["assetId"].endswith("_99") else "pokemon"
    if not include_attachments:
        entries=[entry for entry in entries if entry["assetKind"]=="pokemon"]
    return source_shiny_capabilities(archive,entries)


def source_shiny_capabilities(archive, entries):
    """Do not invent rare palettes for story-only models absent from the game."""
    for entry in entries:
        asset=entry["assetId"]
        path=f"pokemon/data/{asset[:6]}/{asset}/{asset}_rare.trmtr"
        try:
            archive.resolve_trpak_path(path,file_hash=fnv1a64(path))
            entry["shinyAvailable"]=True
        except Exception:
            entry["shinyAvailable"]=False
            entry["missingShinyReason"]="This source model has no original rare material in the supplied game."
    return entries
