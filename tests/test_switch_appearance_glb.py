"""Synthetic animated-mesh fixtures protect variant addressing and unit changes."""
from pathlib import Path
from copy import deepcopy
import struct

import pytest

from rae.platforms.switch.appearance_glb import add_shiny_variant,add_cosmetic_variant,set_cosmetic_axis,replace_base_materials
from rae.platforms.switch.compact_glb import compact_appearances
from rae.platforms.switch.glb_units import centimeters_to_meters
from rae.platforms.switch.gltf.glb_io import GlbData,read_glb

pytestmark=pytest.mark.switch


def overlapping_copies(path,prefix,*,different_role=False):
    fixture(path)
    g=read_glb(path);g.json['materials'][0]['name']='Stick.001_bakeA'
    other=deepcopy(g.json['materials'][0]);other['name']=('Eye' if different_role else 'Stick')+'.001_bakeB'
    g.json['materials'].append(other)
    g.json['meshes'][0]['name']=prefix+'_a'
    mesh=deepcopy(g.json['meshes'][0]);mesh['name']=prefix+'_b';mesh['primitives'][0]['material']=1
    g.json['meshes'].append(mesh);g.write(path)


def test_identical_shared_prop_materials_can_match_across_old_group_labels(tmp_path):
    normal,rare=tmp_path/'normal.glb',tmp_path/'rare.glb'
    overlapping_copies(normal,'old');overlapping_copies(rare,'new')
    add_shiny_variant(normal,rare);g=read_glb(normal)
    refs=[m['extras']['rae']['shinyMaterialIndex'] for m in g.json['materials'][:2]]
    assert refs[0]==refs[1]


def test_same_geometry_and_pixels_cannot_merge_distinct_material_roles(tmp_path):
    normal,rare=tmp_path/'normal.glb',tmp_path/'rare.glb'
    overlapping_copies(normal,'old');overlapping_copies(rare,'new',different_role=True)
    before=normal.read_bytes()
    with pytest.raises(ValueError,match='Ambiguous'):add_shiny_variant(normal,rare)
    assert normal.read_bytes()==before


def fixture(path: Path,*,position=100.,pixel=b"normal"):
    blob=bytearray()
    views=[]
    accessors=[]
    def accessor(values,kind):
        offset=len(blob);payload=struct.pack('<'+str(len(values))+'f',*values);blob.extend(payload)
        views.append({'buffer':0,'byteOffset':offset,'byteLength':len(payload)})
        accessors.append({'bufferView':len(views)-1,'componentType':5126,'count':1,'type':kind})
        return len(accessors)-1
    pos=accessor([position,20.,30.],'VEC3');uv=accessor([.2,.3],'VEC2');indices=accessor([0.],'SCALAR')
    bind=accessor([1,0,0,0,0,1,0,0,0,0,1,0,-100,-20,-30,1],'MAT4')
    translation=accessor([100,20,30],'VEC3')
    views.append({'buffer':0,'byteOffset':len(blob),'byteLength':len(pixel)});blob.extend(pixel)
    doc={'asset':{'version':'2.0'},'buffers':[{'byteLength':len(blob)}],'bufferViews':views,'accessors':accessors,
         'images':[{'bufferView':len(views)-1,'mimeType':'image/png'}],'textures':[{'source':0}],
         'materials':[{'pbrMetallicRoughness':{'baseColorTexture':{'index':0}}}],
         'meshes':[{'name':'body','primitives':[{'material':0,'indices':indices,'attributes':{'POSITION':pos,'TEXCOORD_0':uv}}]}],
         'nodes':[{'translation':[100,20,30]}],'skins':[{'joints':[0],'inverseBindMatrices':bind}],
         'animations':[{'name':'walk','samplers':[{'output':translation}],'channels':[{'sampler':0,'target':{'node':0,'path':'translation'}}]}]}
    GlbData(doc,bytes(blob)).write(path)


def values(glb,index):
    a=glb.json['accessors'][index];v=glb.json['bufferViews'][a['bufferView']]
    return struct.unpack_from('<'+str(v['byteLength']//4)+'f',glb.bin_chunk,v['byteOffset'])


def test_shiny_material_has_embedded_texture_and_does_not_duplicate_animation(tmp_path):
    normal,rare=tmp_path/'normal.glb',tmp_path/'rare.glb';fixture(normal);fixture(rare,pixel=b'rare')
    assert add_shiny_variant(normal,rare)['shinyMaterials']==1
    glb=read_glb(normal);doc=glb.json
    assert len(doc['animations'])==1
    index=doc['materials'][0]['extras']['rae']['shinyMaterialIndex']
    texture=doc['materials'][index]['pbrMetallicRoughness']['baseColorTexture']['index']
    assert doc['textures'][texture]['source']==1
    assert glb.bin_chunk[doc['bufferViews'][doc['images'][1]['bufferView']]['byteOffset']:][:4]==b'rare'
    fixture(rare,position=101.)
    with pytest.raises(ValueError,match='differ'):
        add_shiny_variant(normal,rare)


def test_form_material_is_selected_before_its_own_shiny_material(tmp_path):
    normal,form,rare=[tmp_path/x for x in ('normal.glb','form.glb','rare.glb')]
    for p in (normal,form,rare):fixture(p,pixel=p.stem.encode())
    add_cosmetic_variant(normal,form,rare,'01');set_cosmetic_axis(normal,['Green','Blue'])
    doc=read_glb(normal).json
    index=doc['materials'][0]['extras']['rae']['formMaterialIndices']['01']
    shiny=doc['materials'][index]['extras']['rae']['shinyMaterialIndex']
    assert index!=shiny and len(doc['materials'])==3
    assert doc['extras']['rae']['appearanceVariants']['default']=={'texture':'normal','form':'00'}


def test_meters_conversion_keeps_mesh_bind_and_animation_in_same_coordinate_space(tmp_path):
    path=tmp_path/'units.glb';fixture(path);centimeters_to_meters(path);g=read_glb(path)
    assert values(g,0)==pytest.approx((1.,.2,.3))
    assert values(g,3)[12:15]==pytest.approx((-1.,-.2,-.3))
    assert values(g,4)==pytest.approx((1.,.2,.3))
    assert g.json['nodes'][0]['translation']==pytest.approx((1.,.2,.3))


def test_variant_matches_geometry_after_label_fix_and_ignores_only_zero_noise(tmp_path):
    normal,rare=tmp_path/'normal.glb',tmp_path/'rare.glb'
    fixture(normal,position=0.);fixture(rare,position=1e-20)
    g=read_glb(rare);g.json['meshes'][0]['name']='corrected_source_name';g.write(rare)
    assert add_shiny_variant(normal,rare)['variantGeometryVerified']
    fixture(rare,position=.001)
    with pytest.raises(ValueError,match='differ'):add_shiny_variant(normal,rare)


def test_rebake_compacts_superseded_materials_and_keeps_animation_and_alpha(tmp_path):
    target,normal,rare=[tmp_path/x for x in ('target.glb','normal.glb','rare.glb')]
    for p in (target,normal,rare):fixture(p,pixel=p.stem.encode())
    before=read_glb(target)
    original_animation=values(before,4)
    for p in (normal,rare):
        g=read_glb(p);g.json['materials'][0]['alphaMode']='BLEND';g.write(p)
    replace_base_materials(target,normal);add_shiny_variant(target,rare)
    compact_appearances(target)
    g=read_glb(target);doc=g.json
    assert len(doc['materials'])==len(doc['images'])==len(doc['textures'])==2
    assert values(g,4)==original_animation
    assert doc['animations']==before.json['animations']
    base=doc['meshes'][0]['primitives'][0]['material']
    shiny=doc['materials'][base]['extras']['rae']['shinyMaterialIndex']
    assert shiny!=base
    assert all(m['alphaMode']=='BLEND' and m['extras']['rae']['renderClass']=='blend' for m in doc['materials'])
    assert all(v['byteOffset']%4==0 for v in doc['bufferViews'])
    assert b'target' not in g.bin_chunk


def test_overlapping_meshes_require_identity_when_materials_differ(tmp_path):
    normal,rare=tmp_path/'normal.glb',tmp_path/'rare.glb'
    for path in (normal,rare):
        fixture(path);g=read_glb(path)
        g.json['materials'].append(deepcopy(g.json['materials'][0]))
        g.json['materials'][1]['pbrMetallicRoughness']['baseColorFactor']=[1.,.5,.5,1.]
        other=deepcopy(g.json['meshes'][0]);other['name']='other_mouth'
        other['primitives'][0]['material']=1;g.json['meshes'].append(other);g.write(path)
    assert add_shiny_variant(normal,rare)['shinyMaterials']==2
    g=read_glb(rare);g.json['meshes'][0]['name']='unknown';g.write(rare)
    with pytest.raises(ValueError,match='Ambiguous'):add_shiny_variant(normal,rare)
