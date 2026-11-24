"""Snap courses are discoverable previews without a course export route."""
from __future__ import annotations

import json
import os
import struct
from pathlib import Path

import pytest

from rae.core.modules import PlatformDispatch
from rae.core.modules.types import PreviewRoute
from rae.platforms.switch.container import RomFsFile, SwitchRom
from rae.platforms.switch.gltf.glb_io import read_glb
from rae.platforms.switch.snap_courses import ILLUMINA_SPOT, SNAP_COURSE_MAGIC, UNDERSEA
from rae.platforms.switch.snap_drp import DRPF_MAGIC
from rae.platforms.switch.snap_scene import build_snap_course_preview
from rae.platforms.switch.snap_textures import decode_nutexb

pytestmark = pytest.mark.switch


def test_snap_course_archives_get_preview_only_rows(tmp_path, monkeypatch):
    (tmp_path / "prod.keys").write_text("header_key = " + "00" * 32)
    rom = tmp_path / "game.nsp"
    rom.touch()
    monkeypatch.delenv("RAE_SWITCH_PROD_KEYS", raising=False)
    courses = (ILLUMINA_SPOT, UNDERSEA)
    monkeypatch.setattr(SwitchRom, "romfs_files", lambda _rom: [RomFsFile(c.pack_path, 0, 128) for c in courses])
    monkeypatch.setattr(SwitchRom, "read_file", lambda _rom, _entry, _offset, _size: DRPF_MAGIC.to_bytes(4, "little"))

    assets = PlatformDispatch.scan(rom, rom_platform_id="switch")
    rows = {asset.mapping_label: asset for asset in assets if asset.magic == SNAP_COURSE_MAGIC}
    assert rows.keys() == {course.label for course in courses}
    for course in courses:
        row = rows[course.label]
        assert json.loads(row.data)["romfs_path"] == course.pack_path
        assert PlatformDispatch.preview_route(row, rom_platform_id="switch") is PreviewRoute.MODEL
        assert not PlatformDispatch.export_options_for(row, rom_platform_id="switch")
    assert any(asset.magic == "SWFL" for asset in assets)


def test_nutexb_reads_tiled_bc1_and_converts_color_order():
    pytest.importorskip("texture2ddecoder")
    block = struct.pack("<HHI", 0xF800, 0, 0)
    surface = block.ljust(512, b"\0")
    footer = (
        b" XNT" + b"red".ljust(64, b"\0")
        + struct.pack("<9I", 4, 4, 1, 0x0485, 2, 1, 0x1000, 1, len(surface))
        + b" XET" + struct.pack("<I", 2)
    )
    image = decode_nutexb(surface + bytes(64) + footer)
    assert image.size == (4, 4)
    assert image.getextrema() == ((255, 255), (0, 0), (0, 0), (255, 255))


@pytest.fixture
def snap_rom():
    source = os.environ.get("RAE_TEST_SNAP_ROM")
    if not source:
        pytest.skip("Set RAE_TEST_SNAP_ROM to a local New Pokémon Snap NSP or XCI")
    return Path(source)


def test_illumina_preview_loads_real_terrain_when_rom_supplied(tmp_path, snap_rom):
    out = build_snap_course_preview({"rom": str(snap_rom), "romfs_path": ILLUMINA_SPOT.pack_path}, tmp_path / "preview.glb")
    gltf = read_glb(out).json
    assert gltf["scenes"][0]["name"] == ILLUMINA_SPOT.label
    assert len(gltf["scenes"][0]["nodes"]) == 3
    assert gltf["extras"]["rae"]["freeCamera"]["start"] != gltf["extras"]["rae"]["freeCamera"]["target"]
    assert {mesh["name"] for mesh in gltf["meshes"]} == {
        "groundShape", "rocksetAShape", "rocksetBShape", "rocksetCShape", "rocksetDShape", "rocksetEShape", "skyShape",
    }

    def image_name(texture_info):
        image = gltf["textures"][texture_info["index"]]["source"]
        return gltf["images"][image]["name"]

    for mesh in gltf["meshes"]:
        primitive, = mesh["primitives"]
        assert {"TEXCOORD_0", "TEXCOORD_1"} <= primitive["attributes"].keys()
        material = gltf["materials"][primitive["material"]]
        name = mesh["name"]
        diffuse = material["pbrMetallicRoughness"]["baseColorTexture"]
        prefix = {"groundShape": "SM_ENV_004_sandA_00", "skyShape": "SM_ENV_004_hinagata"}.get(name, "SM_ENV_004_Obj3")
        assert image_name(diffuse) == f"{prefix}_dif.nutexb"
        if name != "skyShape":
            assert image_name(material["normalTexture"]) == f"{prefix}_nor.nutexb"
            shadow = material["occlusionTexture"]
            assert shadow["texCoord"] == 1
            assert f"^{name}^0^Shadow.nutexb" in image_name(shadow)


def test_undersea_preview_loads_real_reef_caves_and_ruins(tmp_path, snap_rom):
    out = build_snap_course_preview({"rom": str(snap_rom), "romfs_path": UNDERSEA.pack_path}, tmp_path / "preview.glb")
    gltf = read_glb(out).json
    scene = gltf["scenes"][0]
    assert scene["name"] == UNDERSEA.label
    groups = {gltf["nodes"][root]["name"].removeprefix(UNDERSEA.model_prefix) for root in scene["nodes"]}
    assert groups == {
        "Ground", "Water", "Groundset1", "Caveset1", "Caveset2", "Caveset3", "Holeset1", "Holeset2",
        "Templeset1", "Templeset2", "Coralrockset1", "Coralrockset2", "Rockwallset1", "Stoneset1", "Seaplantset1",
    }
    camera = gltf["extras"]["rae"]["freeCamera"]
    assert camera["start"] != camera["target"]
    for material in gltf["materials"]:
        surface = material["extras"]["rae"]["snapSurface"]
        if surface != "water":
            assert "baseColorTexture" in material["pbrMetallicRoughness"]
    assert any("emissiveTexture" in material for material in gltf["materials"])
    assert any("occlusionTexture" in material for material in gltf["materials"])
    assert any(material.get("alphaMode") == "MASK" for material in gltf["materials"])
    water, = [material for material in gltf["materials"] if material["extras"]["rae"]["snapSurface"] == "water"]
    assert water["alphaMode"] == "BLEND"
    assert "normalTexture" in water
