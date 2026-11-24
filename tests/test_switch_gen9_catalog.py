from types import SimpleNamespace

import pytest

from rae.platforms.switch.gen9_catalog import GEN9_SPECIES, MODEL_TO_DEX, discover_gen9_forms
from rae.platforms.switch.pokemon_bundle import extract_pokemon_bundle

pytestmark = pytest.mark.switch


def test_generation_filter_covers_each_new_species_once():
    assert set(GEN9_SPECIES) == set(range(906, 1026))
    assert set(MODEL_TO_DEX.values()) == set(GEN9_SPECIES)
    assert len(MODEL_TO_DEX) == 120
    assert MODEL_TO_DEX[1010] == 906
    assert GEN9_SPECIES[1009]["name"] == "Walking Wake"
    assert 1001 not in MODEL_TO_DEX  # Wyrdeer is Gen 8, despite internal ID 1001.


def test_discovery_preserves_form_identity_and_rejects_older_species():
    assets = ["pm1010_00_00", "pm1038_11_00", "pm1038_12_00", "pm1001_00_00", "pm0025_00_00"]

    class Archive:
        _trpfd = SimpleNamespace(trpak_paths=[f"arc/pokemondata{x[:6]}{x}{x}.trmdl.trpak" for x in assets])

        def trpak_in_trpfs(self, _):
            return True

        def resolve_trpak_path(self, path, **_):
            return path + ".trpak"

    entries = discover_gen9_forms(Archive())
    assert [(e["species"], e["formNumber"]) for e in entries] == [(906, 0), (964, 0), (964, 1)]
    assert entries[-1]["label"] == "Palafin_Form12_00"


def test_default_model_can_be_recovered_when_hash_list_only_names_rare(tmp_path):
    asset = "pm1101_00_00"
    prefix = f"pokemon/data/pm1101/{asset}/"

    class Archive:
        def resolve_trpak_path(self, *_args, **_kwargs):
            return "pack"

        def read_by_path(self, _pack, path):
            return path.encode()

    result = extract_pokemon_bundle(
        tmp_path / "Scarlet.nsp", tmp_path / "output", asset, 1004, "Chi-Yu", lambda _: None,
        archive=Archive(), cache=object(), indexed_rows=[("pack", prefix + asset + "_rare.trmdl", 1)])
    assert {row["file"] for row in result["files"]} == {asset + ".trmdl", asset + "_rare.trmdl"}


def test_crystal_mask_attachments_are_source_components_not_standalone_forms():
    assets=['pm1120_11_00','pm1120_11_99','pm1102_12_00']
    class Archive:
        _trpfd=SimpleNamespace(trpak_paths=[f'arc/pokemondata{x[:6]}{x}{x}.trmdl.trpak' for x in assets])
        def trpak_in_trpfs(self,_):return True
        def resolve_trpak_path(self,path,**_):
            if path.endswith('pm1102_12_00_rare.trmtr'):raise KeyError(path)
            return path+'.trpak'
    entries=discover_gen9_forms(Archive())
    assert {e['assetId'] for e in entries}=={'pm1120_11_00','pm1102_12_00'}
    ride=next(e for e in entries if e['species']==1007)
    assert not ride['shinyAvailable'] and 'no original rare' in ride['missingShinyReason']
    attachments=discover_gen9_forms(Archive(),include_attachments=True)
    assert next(e for e in attachments if e['assetId'].endswith('_99'))['assetKind']=='attachment'
