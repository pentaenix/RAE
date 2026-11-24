import hashlib
import json
from pathlib import Path

import pytest

from rae.platforms.switch import pokemon_bundle as bundle
from rae.platforms.switch.gltf.glb_io import GlbData, read_glb
from rae.platforms.switch.pokemon_export import annotate_export

pytestmark = pytest.mark.switch


@pytest.mark.parametrize("path", ["pokemon/data/pm1010/form/../escape", "pokemon/data/pm1010/form/a\\b"])
def test_bundle_refuses_archive_path_escape(path):
    with pytest.raises(ValueError):
        bundle.bundle_relative_path(path, "pokemon/data/pm1010/form/")


def test_exact_form_bundle_preserves_source_and_provenance(tmp_path, monkeypatch):
    prefix = "pokemon/data/pm1010/pm1010_00_00/"
    payloads = {prefix + "pm1010_00_00.trmdl": b"model", prefix + "idle.tranm": b"animation"}

    class Archive:
        def resolve_trpak_path(self, *_args, **_kwargs):
            return "pack"

        def read_by_path(self, _pack, path):
            return payloads[path]

    monkeypatch.setattr(bundle, "open_archive", lambda *_: Archive())
    monkeypatch.setattr(bundle, "hash_cache_for_rom", lambda *_: object())
    # A substring match outside the exact prefix must not leak into this form.
    rows = [("pack", p, i) for i, p in enumerate(payloads)] + [("pack", "other/" + prefix + "bad", 7)]
    monkeypatch.setattr(bundle, "iter_named_trinity_files", lambda *_args, **_kwargs: iter(rows))
    output = tmp_path / "export"
    result = bundle.extract_pokemon_bundle(Path("Scarlet.nsp"), output,
                                          "pm1010_00_00", 906, "Sprigatito", lambda _: None)
    assert len(result["files"]) == 2
    assert (output / "raw/idle.tranm").read_bytes() == b"animation"
    assert result["assetId"] == "pm1010_00_00" and result["species"] == 906
    assert result["files"][0]["sha256"] == hashlib.sha256(b"model").hexdigest()
    assert json.loads((output / "raw_manifest.json").read_text()) == result
    with pytest.raises(FileExistsError):
        bundle.extract_pokemon_bundle(Path("Scarlet.nsp"), output,
                                      "pm1010_00_00", 906, "Sprigatito", lambda _: None)


def test_pilot_does_not_export_legacy_species(tmp_path):
    with pytest.raises(ValueError, match="Gen 8/9"):
        bundle.extract_pokemon_bundle(Path("Scarlet.nsp"), tmp_path, "pm0025_00_00", 25, "Pikachu")


def make_export(path):
    GlbData({
        "asset": {"version": "2.0"}, "animations": [{"name": "idle"}, {"name": "walk"}],
        "skins": [{}], "images": [{"bufferView": 0}], "materials": [{"name": "body"}],
        "meshes": [{"primitives": [{"attributes": {"JOINTS_0": 0, "WEIGHTS_0": 1}}]}],
        "nodes": [{"name": "rig", "children": [1, 2]}, {"mesh": 0, "skin": 0}, {"name": "bone"}],
        "scenes": [{"nodes": [0]}],
    }, b"test").write(path)


def test_annotation_keeps_animation_names_weights_and_embedded_textures(tmp_path):
    path = tmp_path / "model.glb"
    make_export(path)
    report = annotate_export(path, species=906, name="Sprigatito", asset_id="pm1010_00_00",
                             expected_animations={"idle", "walk"})
    doc = read_glb(path).json
    assert report["animations"] == 2 and report["embeddedImages"] == 1
    assert doc["materials"][0]["extras"]["rae"]["platform"] == "switch"
    assert doc["extras"]["rae"]["sourceAssetId"] == "pm1010_00_00"
    assert doc["scenes"][0]["nodes"] == [0, 1]
    assert doc["nodes"][0]["children"] == [2]
    assert read_glb(path).bin_chunk == b"test"


def test_missing_clip_is_an_export_failure(tmp_path):
    path = tmp_path / "model.glb"
    make_export(path)
    with pytest.raises(ValueError, match="animation names"):
        annotate_export(path, species=906, name="Sprigatito", asset_id="pm1010_00_00",
                        expected_animations={"idle", "walk", "sleep"})


@pytest.mark.parametrize('mode,expected',[('BLEND','blend'),('MASK','mask'),('OPAQUE','opaque')])
def test_annotation_preserves_source_transparency_policy(tmp_path,mode,expected):
    path=tmp_path/'model.glb';make_export(path)
    g=read_glb(path);g.json['materials'][0]['alphaMode']=mode;g.write(path)
    annotate_export(path,species=869,name='Alcremie',asset_id='pm0925_11_00',expected_animations={'idle','walk'})
    assert read_glb(path).json['materials'][0]['extras']['rae']['renderClass']==expected
