import struct

import pytest

from rae.platforms.threeds.gf import GfSubMesh
from rae.platforms.threeds.oras_pokemon import package_entries,FORMS
from rae.platforms.threeds.oras_portable import canonical_skin,material_from_bridge

pytestmark=pytest.mark.threeds


def test_oras_package_requires_complete_bounded_offsets():
    good=b'PC'+struct.pack('<H3I',2,16,20,24)+b'BCH\0data'
    assert package_entries(good)==[b'BCH\0',b'data']
    with pytest.raises(ValueError,match='bounds'):package_entries(good[:-1])
    with pytest.raises(ValueError,match='bounds'):package_entries(b'PC\0\0')
    assert set(FORMS)==set(range(2,8)) # ordinary male/female remain preferred Gen 7 models.


def test_duplicate_bch_palette_joints_preserve_combined_weight():
    sub=GfSubMesh('body',joints=[(4,7,4,9)],weights=[(.2,.3,.4,.1)])
    canonical_skin(sub)
    actual=dict(zip(sub.joints[0],sub.weights[0]))
    assert actual[4]==pytest.approx(.6) and actual[7]==pytest.approx(.3)
    assert sum(sub.weights[0])==pytest.approx(1)
    assert len([j for j,w in zip(sub.joints[0],sub.weights[0]) if w>0])==3


def test_empty_skin_row_has_a_finite_single_joint_fallback():
    sub=GfSubMesh('body',joints=[(4,5,6,7)],weights=[(0,0,0,0)])
    canonical_skin(sub)
    assert sub.joints[0]==(0,0,0,0) and sub.weights[0]==(1,0,0,0)


def test_oras_face_render_state_is_opaque_despite_texture_storage_alpha():
    # Original Eye/Mouth output-merger words from the supplied ORAS model.
    # Losing these words incorrectly treats transparent-storage face sheets as
    # cutouts, exposing a costume through the Pokemon's mouth surface.
    words=dict(color_operation=14942464,blend_function=16842752,
               alpha_test=16,depth_color_mask=8017,cull_mode=2)
    state=material_from_bridge({'name':'Mouth','render_state':words,
                                'texture_names':['mouth',None],'texture_units':[]}).render_state
    assert state.render_class()=='opaque'
    assert not state.alpha_test_enabled and state.destination_rgb_factor==0
    assert isinstance(words,dict) # the decoder record remains reusable.
