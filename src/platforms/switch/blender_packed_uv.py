"""Transfer installed packed UVs onto identical imported topology for rebaking."""
import json
from pathlib import Path
import struct
import numpy as np


def _read(path):
    data=Path(path).read_bytes();size=struct.unpack_from('<I',data,12)[0]
    doc=json.loads(data[20:20+size]);blob=data[28+size:]
    def accessor(index):
        a=doc['accessors'][index];v=doc['bufferViews'][a['bufferView']]
        dtype={5121:'u1',5123:'<u2',5125:'<u4',5126:'<f4'}[a['componentType']]
        width={'SCALAR':1,'VEC2':2,'VEC3':3,'VEC4':4,'MAT4':16}[a['type']]
        return np.ndarray((a['count'],width),dtype=dtype,buffer=blob,offset=v.get('byteOffset',0)+a.get('byteOffset',0),strides=(v.get('byteStride',np.dtype(dtype).itemsize*width),np.dtype(dtype).itemsize)).copy()
    return doc,accessor


def packed_uv_map(original,reference=None):
    doc,read=_read(original)
    unit=doc.get('extras',{}).get('rae',{}).get('metersPerSourceUnit',1)
    return {m['name'].removesuffix('_shape'):[{'positions':read(p['attributes']['POSITION'])/unit,
        'uv':read(p['attributes']['TEXCOORD_0']),'indices':read(p['indices']).reshape((-1,3))}
        for p in m['primitives']] for m in doc['meshes']}


def triangle_correspondence(obj,mapping):
    mesh=obj.data;mesh.calc_loop_triangles();parts=mapping[obj.name]
    materials=sorted({t.material_index for t in mesh.loop_triangles})
    if len(parts)!=len(materials):raise ValueError('Material topology changed: '+obj.name)
    permutations=((0,1,2),(0,2,1),(1,0,2),(1,2,0),(2,0,1),(2,1,0))
    basis=None
    for part,material in zip(parts,materials):
        triangles=[t for t in mesh.loop_triangles if t.material_index==material]
        if len(triangles)!=len(part['indices']):raise ValueError('Triangle topology changed: '+obj.name)
        for triangle,indices in zip(triangles,part['indices']):
            local=np.array([mesh.vertices[v].co[:] for v in triangle.vertices])
            expected=part['positions'][indices]
            if basis is None:
                options=(local,local[:,[0,2,1]]*np.array([1,1,-1]),local[:,[0,2,1]]*np.array([1,-1,1]))
                errors=[min(np.max(np.abs(v[list(p)]-expected)) for p in permutations) for v in options]
                basis=int(np.argmin(errors))
            actual=(local if basis==0 else local[:,[0,2,1]]*np.array([1,1,-1] if basis==1 else [1,-1,1]))
            permutation=min(permutations,key=lambda p:np.max(np.abs(actual[list(p)]-expected)))
            if np.max(np.abs(actual[list(permutation)]-expected))>1e-4:raise ValueError('Source triangle order changed: '+obj.name)
            yield part,triangle,indices,permutation


def restore_mesh_uv(obj,mapping):
    layer=obj.data.uv_layers['RAE_Bake']
    for part,triangle,indices,permutation in triangle_correspondence(obj,mapping):
        for corner,source_corner in enumerate(permutation):
            target=part['uv'][indices[corner]]
            layer.data[triangle.loops[source_corner]].uv=(target[0],1-target[1])


def relayout_source_uv(obj,mapping,targets):
    """Give facial charts source UV area instead of their collapsed bind-pose area.

    Only derived UV accessors change. Source geometry, vertex order and skinning
    remain intact. Existing packed vertices must already split source UV seams.
    """
    layer=next(u for u in obj.data.uv_layers if u.active_render)
    selected={};seen={}
    for part,triangle,indices,permutation in triangle_correspondence(obj,mapping):
        material=obj.material_slots[triangle.material_index].material
        if material.get('repair_source',material.name.split('.')[0]) not in targets:continue
        key=id(part);selected[key]=part;seen.setdefault(key,{})
        for corner,source_corner in enumerate(permutation):
            uv=layer.data[triangle.loops[source_corner]].uv
            value=np.array([uv.x,1-uv.y],dtype='float32');index=int(indices[corner])
            if index in seen[key] and np.max(np.abs(seen[key][index]-value))>1e-5:
                raise ValueError('Source UV seam requires a split vertex: '+obj.name)
            seen[key][index]=value
    for key,part in selected.items():
        values=np.array(list(seen[key].values()));low=values.min(0);span=np.maximum(values.max(0)-low,1e-6)
        for index,value in seen[key].items():part['uv'][index]=.025+.95*(value-low)/span
        part['sourceUvRelayout']=True
    return len(selected)
