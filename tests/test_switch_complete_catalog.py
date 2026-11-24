from types import SimpleNamespace

import pytest

from rae.platforms.switch.complete_catalog import ALL_MODEL_TO_DEX,discover_swsh_forms,describe_assets

pytestmark=pytest.mark.switch


def test_new_species_identity_map_covers_all_missing_species_without_model_id_guessing():
    assert set(range(808,1026))<=set(ALL_MODEL_TO_DEX.values())
    assert ALL_MODEL_TO_DEX[948]==810
    assert ALL_MODEL_TO_DEX[938]==888
    assert ALL_MODEL_TO_DEX[1001]==899
    assert ALL_MODEL_TO_DEX[891]==808


def test_older_species_only_admit_new_regional_gmax_and_world_cap_models():
    assets=['pm0025_00','pm0025_25','pm0025_81_00','pm0052_00_31','pm0948_00_00']
    forms=discover_swsh_forms([SimpleNamespace(path=f'/bin/archive/pokemon/{a}.gfpak') for a in assets])
    assert {e['assetId'] for e in forms}==set(assets)-{'pm0025_00'}
    assert {e['species'] for e in forms}=={25,52,810}
    assert {e['species'] for e in describe_assets(['pm0483_11_00','pm0483_12_00'],source='sv')}=={483}
    assert describe_assets(['pm0483_11_00'],source='sv')==[]
