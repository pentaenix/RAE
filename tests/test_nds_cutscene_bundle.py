from __future__ import annotations

from rae.core.assets import Asset
from rae.platforms.nds.cutscene_bundle import named_animation_siblings


def _asset(index: int, magic: str, name: str) -> Asset:
    extension = {
        "BMD0": ".nsbmd",
        "BCA0": ".nsbca",
        "BTA0": ".nsbta",
    }[magic]
    encoded_name = name.encode("ascii") + b"\x00"
    data = magic.encode("ascii") + b"\x00" * 12 + encoded_name
    return Asset(
        asset_id=f"asset-{index}",
        virtual_path=f"a/1/5/8/file_{index:04d}.bin{extension}",
        kind="Model" if magic == "BMD0" else "Animation",
        magic=magic,
        extension=extension,
        data=data,
        original_data=data,
        container_chain=("a/1/5/8",),
    )


def test_matches_only_the_named_animation_bundle_in_large_cutscene_folder() -> None:
    royal_model = _asset(42, "BMD0", "c_cruiser_port02")
    assets = [
        _asset(40, "BTA0", "c_cruiser_port01"),
        _asset(41, "BCA0", "c_cruiser_port02"),
        royal_model,
        _asset(43, "BTA0", "c_cruiser_port02"),
        _asset(44, "BCA0", "c_cruiser_port03"),
    ]

    matches = named_animation_siblings(royal_model, assets)

    assert [asset.virtual_path for asset in matches] == [
        "a/1/5/8/file_0041.bin.nsbca",
        "a/1/5/8/file_0043.bin.nsbta",
    ]


def test_rejects_matching_names_that_are_too_far_from_the_model() -> None:
    model = _asset(100, "BMD0", "shared_name")
    distant = _asset(140, "BTA0", "shared_name")

    assert named_animation_siblings(model, [model, distant]) == []
