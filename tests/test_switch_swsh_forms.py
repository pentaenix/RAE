import pytest

from rae.platforms.switch.gltf.glb_io import GlbData,read_glb
from rae.platforms.switch.swsh_forms import annotate_alcremie,SWEETS,FLAVOR_MOUTHS

pytestmark=pytest.mark.switch


def test_alcremie_exposes_each_source_sweet_and_only_its_flavor_mouth(tmp_path):
    path=tmp_path/'alcremie.glb'
    nodes=[{'name':f'pm0925_{name}Skin','mesh':0} for name in (*SWEETS,*FLAVOR_MOUTHS)]
    GlbData({'nodes':nodes,'extras':{'rae':{'appearanceVariants':{'default':{},'axes':[]}}}},b'').write(path)
    assert annotate_alcremie(path,'pm0925_12_00')
    g=read_glb(path).json
    assert len(g['extras']['rae']['appearanceVariants']['axes'][0]['options'])==7
    for i in range(7):assert g['nodes'][i]['extras']['rae']['visibleForForms']==[f'{i:02}']
    assert 'extras' not in g['nodes'][8] # PinkMouth belongs to flavor 12.
    assert all(n['extras']['rae']['visibleForForms']==['__hidden_source_alternative__']
               for i,n in enumerate(g['nodes'][7:]) if i!=1)
    assert not annotate_alcremie(path,'pm0925_81_00')


def test_alcremie_rejects_incomplete_source_decoration_groups(tmp_path):
    path=tmp_path/'incomplete.glb'
    GlbData({'nodes':[{'name':'StrawberrySkin','mesh':0}]},b'').write(path)
    with pytest.raises(ValueError,match='incomplete'):annotate_alcremie(path,'pm0925_11_00')
