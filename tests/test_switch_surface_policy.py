import pytest
from rae.platforms.switch.swsh_surface_policy import bake_sphere_reflection

pytestmark=pytest.mark.switch


def test_authored_eye_pupils_are_not_overwritten_by_an_object_space_reflection():
    for name in ['Eye','LEye','REye','EyeVco','REyeA']:
        assert not bake_sphere_reflection(name,{'SphereMapEnable':True})


def test_body_metal_and_ice_keep_their_source_sphere_map():
    for name in ['BodyEnv00','BodyBEnv','BodyCVcoEnv01','Ice']:
        assert bake_sphere_reflection(name,{'SphereMapEnable':True})
        assert not bake_sphere_reflection(name,{'SphereMapEnable':False})
