"""A collapsed bind-pose chart must not determine facial texture resolution."""
from types import SimpleNamespace as NS
import numpy as np
import pytest
from rae.platforms.switch.blender_packed_uv import relayout_source_uv,restore_mesh_uv

pytestmark=pytest.mark.switch


def fixture(source_name='Eye'):
    coords=np.array([[0,0,0],[1,0,0],[0,1,0]],dtype='float32')
    old=np.array([[.4,.4],[.40001,.4],[.4,.40001]],dtype='float32')
    uv=NS(name='source',active_render=True,data=[NS(uv=NS(x=x,y=y)) for x,y in [(0,0),(1,0),(0,1)]])
    tri=NS(vertices=[2,0,1],loops=[2,0,1],material_index=0)
    class Layers(list):
        def __getitem__(self,key):return self[1] if key=='RAE_Bake' else super().__getitem__(key)
    layers=Layers([uv,NS(data=[NS(uv=None) for _ in range(3)])])
    mesh=NS(vertices=[NS(co=v) for v in coords],loop_triangles=[tri],calc_loop_triangles=lambda:None,uv_layers=layers)
    class Material(dict):name=source_name
    obj=NS(name='face',data=mesh,material_slots=[NS(material=Material(repair_source=source_name))])
    mapping={'face':[{'positions':coords.copy(),'uv':old.copy(),'indices':np.array([[0,1,2]])}]}
    return obj,mapping,coords,old


def test_source_face_uv_area_survives_a_collapsed_bind_pose_and_corner_permutation():
    obj,mapping,coords,old=fixture()
    assert relayout_source_uv(obj,mapping,{'Eye'})==1
    part=mapping['face'][0]
    np.testing.assert_allclose(part['uv'],[[.025,.975],[.975,.975],[.025,.025]],atol=1e-6)
    assert np.prod(np.ptp(part['uv'],axis=0))>1e8*np.prod(np.ptp(old,axis=0))
    np.testing.assert_array_equal(part['positions'],coords)
    restore_mesh_uv(obj,mapping)
    np.testing.assert_allclose([x.uv for x in obj.data.uv_layers['RAE_Bake'].data],[[.025,.025],[.975,.025],[.025,.975]],atol=1e-6)


def test_unrelated_body_uvs_remain_exact():
    obj,mapping,_,old=fixture('Body')
    assert relayout_source_uv(obj,mapping,{'Eye'})==0
    np.testing.assert_array_equal(mapping['face'][0]['uv'],old)
