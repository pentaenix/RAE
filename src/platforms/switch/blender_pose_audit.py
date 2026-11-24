"""Compare portable skin-joint poses with the evaluated immutable source scene."""
import json
import hashlib
import math
from pathlib import Path
import sys
import bpy
import numpy as np
from mathutils import Matrix,Quaternion,Vector


def audit(row):
    from blender_animation_export import read_glb
    job=row['job'];directory=Path(row['directory']);g=read_glb(directory/row.get('poseAuditModel','final.glb'));doc=g.json
    bpy.ops.wm.open_mainfile(filepath=str(Path(job['glb']).with_suffix('.blend')))
    arm=next(o for o in bpy.context.scene.objects if o.type=='ARMATURE')
    bones={b.name:b for b in arm.pose.bones};nodes=doc['nodes'];parents={c:i for i,n in enumerate(nodes) for c in n.get('children',[])}
    widths={'SCALAR':1,'VEC2':2,'VEC3':3,'VEC4':4,'MAT4':16};types={5126:'<f4',5125:'<u4',5123:'<u2',5121:'u1'}
    def accessor(index):
        a=doc['accessors'][index];v=doc['bufferViews'][a['bufferView']];dtype=np.dtype(types[a['componentType']]);width=widths[a['type']]
        return np.ndarray((a['count'],width),dtype=dtype,buffer=g.bin_chunk,offset=v.get('byteOffset',0)+a.get('byteOffset',0),strides=(v.get('byteStride',width*dtype.itemsize),dtype.itemsize)).copy()
    def matrix(n):
        if 'matrix' in n:return Matrix([n['matrix'][r::4] for r in range(4)])
        q=n.get('rotation',[0,0,0,1]);return Matrix.LocRotScale(Vector(n.get('translation',[0,0,0])),Quaternion((q[3],*q[:3])),Vector(n.get('scale',[1,1,1])))
    def globals_for(local):
        result={}
        def visit(i):
            if i not in result:result[i]=visit(parents[i])@local[i] if i in parents else local[i]
            return result[i]
        for i in range(len(nodes)):visit(i)
        return result
    rest=globals_for([matrix(n) for n in nodes]);basis=Matrix.Rotation(-math.pi/2,4,'X')
    targets={i:bones[n['name']] for i,n in enumerate(nodes) if n.get('name') in bones}
    align={i:(basis@arm.matrix_world@b.bone.matrix_local).inverted_safe()@rest[i] for i,b in targets.items()}
    positions=[accessor(p['attributes']['POSITION'])[:,1] for m in doc['meshes'] for p in m['primitives']]
    height=max(v.max() for v in positions)-min(v.min() for v in positions)
    manifest=json.loads((Path(job['output'])/'animation_manifest.json').read_text());meta={c['name']:c for c in manifest['animations']}
    errors=[];sample_count=0
    for clip in doc['animations']:
        if not any(key in clip['name'] for key in ('defaultwait01','walk01_loop','run01_loop')):continue
        action=bpy.data.actions[clip['name']];arm.animation_data.action=action
        if action.slots:arm.animation_data.action_slot=action.slots[0]
        for b in arm.pose.bones:b.matrix_basis=Matrix.Identity(4)
        start,end=map(int,action.frame_range);fps=meta[clip['name']]['fps']
        channels=[(c,accessor(clip['samplers'][c['sampler']]['input']).ravel(),accessor(clip['samplers'][c['sampler']]['output'])) for c in clip['channels']]
        for frame in sorted({0,(end-start)//2,end-start}):
            bpy.context.scene.frame_set(start+frame);bpy.context.view_layer.update();seconds=frame/fps;trs=[dict(n) for n in nodes]
            for c,times,values in channels:
                idx=min(max(int(np.searchsorted(times,seconds,side='right'))-1,0),len(times)-1);value=values[idx]
                if idx+1<len(times) and times[idx+1]>times[idx]:
                    t=float(np.clip((seconds-times[idx])/(times[idx+1]-times[idx]),0,1))
                    if c['target']['path']=='rotation':
                        a,b=value,values[idx+1];q=Quaternion((a[3],*a[:3])).slerp(Quaternion((b[3],*b[:3])),t);value=[q.x,q.y,q.z,q.w]
                    else:value=value*(1-t)+values[idx+1]*t
                trs[c['target']['node']][c['target']['path']]=list(map(float,value));trs[c['target']['node']].pop('matrix',None)
            actual=globals_for([matrix(n) for n in trs]);active=set();vis=clip.get('extras',{}).get('rae',{}).get('meshVisibility',{})
            for n in nodes:
                if 'mesh' not in n or 'skin' not in n:continue
                flags=vis.get(n.get('name'),[True])
                if flags and not flags[min(frame,len(flags)-1)]:continue
                joints=doc['skins'][n['skin']]['joints']
                for p in doc['meshes'][n['mesh']]['primitives']:
                    if 'JOINTS_0' not in p['attributes']:continue
                    slots=accessor(p['attributes']['JOINTS_0']);weights=accessor(p['attributes']['WEIGHTS_0'])
                    active.update(joints[int(s)] for s in np.unique(slots[weights>.0001]))
            for i in active&targets.keys():
                expected=basis@arm.matrix_world@targets[i].matrix@align[i];position=(actual[i].translation-expected.translation).length/max(float(height),.001)
                linear=max((actual[i].col[k].xyz-expected.col[k].xyz).length/max(expected.col[k].xyz.length,.001) for k in range(3))
                errors.append({'bone':nodes[i]['name'],'clip':clip['name'],'frame':frame,'positionErrorHeight':position,'basisRelativeError':linear})
            sample_count+=1
    maximum_position=max((e['positionErrorHeight'] for e in errors),default=0);maximum_basis=max((e['basisRelativeError'] for e in errors),default=0)
    errors.sort(key=lambda e:max(e['positionErrorHeight']/.002,e['basisRelativeError']/.01),reverse=True)
    result={'id':row['id'],'modelSha256':hashlib.sha256((directory/row.get('poseAuditModel','final.glb')).read_bytes()).hexdigest(),'samples':sample_count,'maxPositionErrorHeight':maximum_position,'maxBasisRelativeError':maximum_basis,'needsRepair':maximum_position>.002 or maximum_basis>.01,'worst':errors[:8]}
    (directory/row.get('poseAuditOutput','pose_audit.json')).write_text(json.dumps(result,indent=2)+'\n');print('POSE_AUDIT',row['id'],result['needsRepair'],maximum_position,maximum_basis,flush=True)
    return result


if __name__=='__main__':
    sys.path.insert(0,str(Path(__file__).parent));args=sys.argv[sys.argv.index('--')+1:]
    catalog=json.loads(Path(args[0]).read_text());errors=[]
    for row in catalog['models']:
        try:audit(row)
        except Exception as error:
            import traceback;traceback.print_exc();errors.append({'id':row['id'],'error':str(error)})
    if errors:raise ValueError(errors)
