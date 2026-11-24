"""Evaluate eyelid sampler graphs without requiring a Blender installation."""
import importlib
import math
import sys
from types import SimpleNamespace as NS
import pytest

pytestmark=pytest.mark.switch


class Socket:
    def __init__(self,node):
        self.node=node;self.links=[];self.default_value=None

    @property
    def is_linked(self):return bool(self.links)


class Sockets(dict):
    def __init__(self,node):super().__init__();self.node=node
    def __missing__(self,key):
        self[key]=Socket(self.node);self[key].key=key;return self[key]


class Node:
    def __init__(self,kind):
        self.type=kind;self.inputs=Sockets(self);self.outputs=Sockets(self);self.image=None


class Nodes(list):
    def __getitem__(self,key):return self[0] if key=='Group' else super().__getitem__(key)
    def new(self,kind):
        node=Node({'ShaderNodeTexImage':'TEX_IMAGE','ShaderNodeUVMap':'UVMAP',
                   'ShaderNodeMapping':'MAPPING','ShaderNodeVectorMath':'VECT_MATH',
                   'ShaderNodeSeparateXYZ':'SEPARATE','ShaderNodeCombineXYZ':'COMBINE','ShaderNodeMath':'MATH'}[kind])
        self.append(node);return node


def connect(source,target):
    target.links=[NS(from_socket=source,from_node=source.node)]


def vector(socket,uv):
    node=socket.node
    def incoming(name):return vector(node.inputs[name].links[0].from_socket,uv)
    if node.type=='UVMAP':return uv
    if node.type=='VECT_MATH':
        assert node.operation=='FRACTION'
        return tuple(v-math.floor(v) for v in incoming(0))
    if node.type=='MAPPING':
        return tuple(v*s+t for v,s,t in zip(incoming('Vector'),node.inputs['Scale'].default_value,node.inputs['Location'].default_value))
    if node.type=='SEPARATE':return incoming('Vector')[{'X':0,'Y':1,'Z':2}[socket.key]]
    if node.type=='MATH':
        assert node.operation=='FRACT'
        value=incoming(0);return value-math.floor(value)
    if node.type=='COMBINE':return (incoming('X'),incoming('Y'),0)
    raise AssertionError('Unexpected sampler graph node: '+node.type)


def sampler(monkeypatch,tmp_path,animated):
    fake=NS(data=NS(images=NS(load=lambda path,**kw:NS(filepath=path))))
    monkeypatch.setitem(sys.modules,'bpy',fake)
    name='rae.platforms.switch.blender_source_uv'
    monkeypatch.delitem(sys.modules,name,raising=False)
    module=importlib.import_module(name)
    nodes=Nodes([Node('GROUP')]);material=NS(node_tree=NS(nodes=nodes,links=NS(new=connect)))
    source={'textures':{'LowerEyelidColorMap':'lid.bntx'},'colors':{},'shaders':{'Eye':{}}}
    (tmp_path/'lid.png').touch()
    module.repair_uvs(material,source,animated,tmp_path,'source')
    return next(n for n in nodes if n.type=='TEX_IMAGE')


def test_open_lid_repeats_the_face_chart_before_its_animated_slide(monkeypatch,tmp_path):
    node=sampler(monkeypatch,tmp_path,{'UVScaleOffset4':[1,1,0,0]})
    output=node.inputs['Vector'].links[0].from_socket
    # Tadbulb's source face is on a later UV tile, not inside [0,1].
    assert vector(output,(.25,1.8,0))==pytest.approx((.25,.8,0))
    assert vector(output,(.25,2.8,0))==pytest.approx((.25,.8,0))


def test_slid_lid_clips_outside_the_chart_instead_of_repeating_or_smearing(monkeypatch,tmp_path):
    node=sampler(monkeypatch,tmp_path,{'UVScaleOffset4':[1,1,0,-.4]})
    output=node.inputs['Vector'].links[0].from_socket
    assert vector(output,(.25,1.8,0))==pytest.approx((.25,1.2,0))
    assert node.extension=='CLIP','An open/slid eyelid must sample transparent outside its own sheet'


@pytest.mark.parametrize('offset',[1,-1,.5,-.231])
def test_lid_repeats_horizontally_after_translation_while_vertical_slide_still_clips(monkeypatch,tmp_path,offset):
    node=sampler(monkeypatch,tmp_path,{'UVScaleOffset4':[1,1,offset,-.4]})
    output=node.inputs['Vector'].links[0].from_socket
    assert vector(output,(.25,1.8,0))==pytest.approx(((.25+offset)%1,1.2,0))
    assert node.extension=='CLIP'
