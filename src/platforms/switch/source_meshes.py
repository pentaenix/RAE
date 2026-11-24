"""Original GFBMDL mesh groups and the legacy off-by-one export aliases."""
from pathlib import Path
import sys


def mesh_names(job):
    deps=Path(job['dependencies']);sys.path[:0]=[str(deps/'python'),str(deps/'pokemon_switch')]
    from GFLib.Model.Model import Model
    root=Model.GetRootAsModel((Path(job['raw'])/job['modelFile']).read_bytes(),0)
    aliases={};names=[]
    for i in range(root.GroupsLength()):
        index=root.Groups(i).BoneIndex();name=root.Bones(index).Name().decode();names.append(name)
        if index>0:aliases[root.Bones(index-1).Name().decode()]=name
    return {'names':names,'legacyAliases':aliases}
