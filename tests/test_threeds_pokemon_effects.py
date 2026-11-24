import struct
import pytest

from rae.platforms.threeds.gf import GfMaterial,GfModel
from rae.platforms.threeds.pokemon_effects import shader_entries,effect_pass,portable_colors,prepare_portable_surfaces
from rae.platforms.threeds.pokemon_effects import effect_motion

pytestmark=pytest.mark.threeds


def test_surface_default_needs_uv_tracks_not_just_body_visibility(monkeypatch):
    from rae.platforms.threeds import motion
    payload={'clips':[{'id':'body','loop':True,'tracks':[],'meshVisibility':{'body':[True]}},
        {'id':'attack','loop':False,'tracks':[{'material':'FireCoreA'}]},
        {'id':'idle_uv','loop':True,'tracks':[{'material':'FireCoreB'}],'meshVisibility':{'body':[True]}}],
        'defaultClip':'body','overlayClips':['attack']}
    monkeypatch.setattr(motion,'build_world_map_material_motion',lambda *a,**k:payload)
    result=effect_motion([],None,{'FireCoreA','FireCoreB'})
    assert result['defaultClip']=='idle_uv'
    assert len(result['clips'])==2 and all(c['loop'] for c in result['clips'])
    assert all(c['tracks'] and 'meshVisibility' not in c for c in result['clips'])
    assert 'overlayClips' not in result


def test_ps_shader_bank_is_bounded_and_distinct_from_pc_material_bank():
    package=b'PS'+struct.pack('<H3I',2,16,20,24)+b'firstwo!'
    assert shader_entries(package)==[b'firs',b'two!']
    with pytest.raises(ValueError,match='bounds'):shader_entries(package[:-1])
    with pytest.raises(ValueError,match='header'):shader_entries(b'PS\xff\xff1234')
    assert shader_entries(b'not a shader pack')==[]


def test_distortion_pass_is_distinct_from_the_visible_surface():
    for shader in ('FireCore_FireWingGRE','FireGeom_lizardonGRE'):
        assert effect_pass(GfMaterial('effect',fragment_shader_name=shader))=='intermediate'
    assert effect_pass(GfMaterial('effect',fragment_shader_name='FireSten_lizardonGRE'))=='flame_or_smoke'
    assert effect_pass(GfMaterial('overlay',fragment_shader_name='PDC_pm_betbeton_BetoGRE'))=='wet_surface'
    assert effect_pass(GfMaterial('FireDecoration',fragment_shader_name='PDC_Body_ShadowALW')) is None


def test_specular_mask_rgb_does_not_blacken_base_color_but_alpha_is_retained():
    # Texture * fragment lighting; vertex alpha is a scalar mask, not RGB tint.
    mat=GfMaterial('body',fragment_shader_name='PDC_BodySpc',
        tev_stages=({'source':3|(1<<4),'operand':0,'combiner':1},))
    colors=[(.0,.25,.5,.6)]
    assert portable_colors(mat,colors)==[(1,1,1,.6)]
    mat.tev_stages=({'source':3,'operand':0,'combiner':1},) # texture * primary RGB
    assert portable_colors(mat,colors)==colors
    mat.fragment_shader_name='world_shader'
    assert portable_colors(mat,colors)==colors


def test_smoke_uses_its_authored_volume_and_keeps_compositor_hidden():
    colors=((255,255,255,0),)*3+((189,182,133,255),(117,107,46,127),(255,255,255,0))
    core=GfMaterial('FireCoreA',fragment_shader_name='FireCore_FireWingGRE',constant_colors=colors)
    geometry=GfMaterial('FireGeomA',fragment_shader_name='FireGeom_lizardonGRE')
    stencil=GfMaterial('FireStenA',fragment_shader_name='FireSten_dogarsGRE',constant_colors=colors)
    model=GfModel('smoke',materials=[core,geometry,stencil]);prepare_portable_surfaces(model)
    assert effect_pass(core)=='flame_or_smoke'
    assert effect_pass(geometry)==effect_pass(stencil)=='intermediate'
    assert core.constant_colors[3:5]==colors[3:5]
    assert len(core.tev_stages)==6
    assert core.tev_stages[2]['operand']==0x1500 # inverse white capture background
    assert core.tev_stages[3]['combiner']==0x10000 # source smoke opacity
    assert core.tev_stages[-1]['source']==0x0fff0fff
