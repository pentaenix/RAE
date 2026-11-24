import pytest
from rae.platforms.switch.swsh_material_policy import zero_light_envelope
from rae.platforms.switch.swsh_material_uv import color_uv_transform,blender_color_uv_transform

pytestmark=pytest.mark.switch


def test_zero_light_emission_envelope_is_neutral_without_hiding_opaque_black():
    black=((0,0),(0,0),(0,0),(0,255))
    values={'BlendMode':5,'PreMultiplieMode':1};flags={'DepthWrite':False}
    assert zero_light_envelope(values,flags,black)
    assert not zero_light_envelope(values,{'DepthWrite':True},black)
    assert not zero_light_envelope({'BlendMode':0,'PreMultiplieMode':1},flags,black)
    assert not zero_light_envelope(values,flags,((0,1),(0,0),(0,0),(0,255)))


def test_gfbmdl_translation_precedes_scale_and_base_shift():
    scale,offset=color_uv_transform({'ColorUVScaleU':2,'ColorUVScaleV':4,
        'ColorUVTranslateU':.25,'ColorUVTranslateV':-.5,'ColorBaseU':-.5,'ColorBaseV':1})
    assert scale==(2,4) and offset==(0,-1)
    # Matches the original shader's shift + scale * (uv + translate).
    assert tuple(s*v+o for s,v,o in zip(scale,(.2,.3),offset))==pytest.approx((.4,.2))


def test_layer_transform_and_base_transform_are_independent():
    values={'ColorUVScaleU':2,'Layer1UVScaleV':3,'Layer1BaseU':.5}
    assert color_uv_transform(values)==((2,1),(0,0))
    assert color_uv_transform(values,layer=True)==((1,3),(.5,0))


@pytest.mark.parametrize('translation',[0,.25,.5,.75])
def test_eye_rows_slide_in_source_v_direction_after_blender_uv_flip(translation):
    values={'ColorUVScaleU':2,'ColorBaseU':-.5,'ColorUVTranslateV':translation}
    scale,offset=blender_color_uv_transform(values)
    # Kubfu's closed eye is row 3. A positive Blender offset selects row 1.
    bottom_v=.88
    assert (scale[1]*bottom_v+offset[1])%1==pytest.approx((bottom_v-translation)%1)


def test_scaled_and_shifted_sampler_matches_source_coordinates_in_both_spaces():
    values={'ColorUVScaleU':2,'ColorUVScaleV':4,'ColorUVTranslateU':.25,
            'ColorUVTranslateV':-.5,'ColorBaseU':-.5,'ColorBaseV':1}
    scale,offset=blender_color_uv_transform(values)
    assert tuple(s*v+o for s,v,o in zip(scale,(.2,.7),offset))==pytest.approx((.4,.8))
