from types import SimpleNamespace
import pytest
from rae.platforms.switch.source_tracks import packed_bools, dense_track, sample_keys
from rae.platforms.switch.sv_material_animation import read_tracm
from rae.platforms.switch.source_materials import emits_black_layers, uv_parameter, portable_emission_required

pytestmark=pytest.mark.switch


def test_trimmed_visibility_payload_holds_the_last_encoded_state():
    assert packed_bools(bytes([0b10000001]),11)==[True,False,False,False,False,False,False,True,True,True,True]
    assert packed_bools(b'',3)==[False]*3
    assert dense_track(SimpleNamespace(**{'bool':False}),3,boolean=True)==[False]*3


def test_duplicate_source_keys_and_discrete_mesh_switches():
    assert sample_keys([0,3,3,5],[0,1,4,8],3)==4
    assert sample_keys([0,3],[0,1],2,step=True)==0
    assert sample_keys([0,3],[0,6],2)==4


def test_sv_omitted_false_field_still_hides_move_mesh():
    # Synthetic 21-frame TRACM: a fixed false field omitted by FlatBuffers.
    payload=bytes.fromhex('0c00000008000e000800040008000000200000001000000000000a000c000000080004000a0000003c00000015000000010000001400000010000e0008000000000000000000040010000000140000003400000000000a0008000000000004000a0000000c00000008000c000b000400080000000c000000000000010400040004000000090000006d6f76655f70726f70000000')
    state=read_tracm(payload)
    assert state['frames']==21 and state['fps']==60
    assert state['visibility']['move_prop']==[False]*21


def test_black_diffuse_layers_must_retain_colored_source_emission():
    material={'floats':{'EmissionIntensityLayer1':1},'colors':{'BaseColorLayer1':[0,0,0,1],'EmissionColorLayer1':[2,.2,0,1]}}
    assert emits_black_layers(material)
    material['floats']['EmissionIntensityLayer1']=0
    assert not emits_black_layers(material)


def test_upper_and_lower_lids_have_independent_source_uv_controllers():
    assert uv_parameter('UpperEyelidColorMap')=='UVScaleOffset3'
    assert uv_parameter('LowerEyelidColorMap')=='UVScaleOffset4'
    assert uv_parameter('BaseColorMap')=='UVScaleOffset'
    assert uv_parameter('BaseColorMap1')=='UVScaleOffset1'


def test_nonzero_eye_diffuse_does_not_suppress_authored_emission_highlights():
    source={'shaders':{'Eye':{}},'floats':{'EmissionIntensityLayer4':1},
            'colors':{'BaseColorLayer4':[.0129,.0129,.0129,1],'EmissionColorLayer4':[1,1,1,1]}}
    assert not emits_black_layers(source)
    assert portable_emission_required(source)
    source['shaders']={'SSS':{}}
    assert portable_emission_required(source)


def test_unlit_eyes_and_flames_use_base_color_as_their_emission():
    source={'shaders':{'Unlit':{}},'floats':{'EmissionIntensity':1.5},
            'colors':{'BaseColor':[.96,.64,.007,1]}}
    assert portable_emission_required(source)
    source['floats']['EmissionIntensity']=0
    assert not portable_emission_required(source)


def test_global_emission_maps_do_not_require_a_constant_color_parameter():
    source={'shaders':{'Standard':{}},'floats':{'EmissionIntensity':.2},
            'colors':{},'textures':{'EmissionColorMap':'body_emi.bntx'}}
    assert portable_emission_required(source)
    source['floats']['EmissionIntensity']=0
    assert not portable_emission_required(source)
