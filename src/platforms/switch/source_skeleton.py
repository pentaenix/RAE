"""Original bone ancestry, including rigs flattened by the portable exporter."""
from pathlib import Path
import sys


def source_parents(job):
    deps = Path(job['dependencies'])
    sys.path[:0] = [str(deps / 'python'), str(deps / 'pokemon_switch')]
    raw = Path(job['raw'])
    if job.get('sourceFormat') == 'gfbmdl':
        from GFLib.Model.Model import Model
        model = Model.GetRootAsModel((raw / job['modelFile']).read_bytes(), 0)
        bones = [model.Bones(i) for i in range(model.BonesLength())]
        return {b.Name().decode(): bones[b.Parent()].Name().decode() if 0 <= b.Parent() < len(bones) else None for b in bones}
    from Titan.Model.TRSKL import TRSKL
    result = {}
    for path in sorted(raw.glob('*.trskl')):
        model = TRSKL.GetRootAsTRSKL(path.read_bytes(), 0)
        bones = [model.TransformNodes(i) for i in range(model.TransformNodesLength())]
        result.update({b.Name().decode(): bones[b.ParentIdx()].Name().decode() if 0 <= b.ParentIdx() < len(bones) else None for b in bones})
    return result
