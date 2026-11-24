"""Regression coverage for scale-compensated SV prop detection."""
from types import SimpleNamespace as Obj

import pytest

from rae.platforms.switch.blender_pose_hierarchy import _scale_animated_bones,retain_auxiliary_skin_roots

pytestmark = pytest.mark.switch


def action(path, values):
    curve = Obj(data_path=path, keyframe_points=[Obj(co=Obj(y=value)) for value in values])
    return Obj(layers=[Obj(strips=[Obj(channelbags=[Obj(fcurves=[curve])])])])


def test_hidden_prop_scale_is_detected_without_selecting_normal_body_motion():
    actions = [action('pose.bones["feeler_13"].scale', [1, .001, 1]),
               action('pose.bones["head"].scale', [1, 1.05, .95]),
               action('pose.bones["waist"].location', [0, 1000, 0])]
    assert _scale_animated_bones(actions) == {"feeler_13"}


def test_zero_negative_and_large_prop_scales_are_checked_by_magnitude():
    actions = [action('pose.bones["hidden"].scale', [0]),
               action('pose.bones["mirrored"].scale', [-1]),
               action('pose.bones["compensated"].scale', [1000])]
    assert _scale_animated_bones(actions) == {"hidden", "compensated"}


def test_static_actions_need_no_prop_hierarchy_change():
    assert _scale_animated_bones([]) == set()
    assert _scale_animated_bones([Obj(layers=[])]) == set()


def test_exporter_neutral_joint_retains_ancestor_transform_under_common_root():
    doc={'nodes':[{'name':'pose'},{'name':'neutral'}, {'rotation':[.7,0,0,.7],'children':[1,3]},
                  {'mesh':0},{'name':'RAE_SkeletonRoot','children':[0]}],
         'skins':[{'joints':[0,1],'skeleton':4}],'scenes':[{'nodes':[2,4]}]}
    retain_auxiliary_skin_roots(doc,4)
    assert doc['nodes'][4]['children']==[0,2]
    assert doc['nodes'][2]=={'rotation':[.7,0,0,.7],'children':[1,3]}
    assert doc['scenes'][0]['nodes']==[4]
    retain_auxiliary_skin_roots(doc,4)
    assert doc['nodes'][4]['children']==[0,2]
