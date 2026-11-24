"""Bake evaluated source poses into independent joints, retaining mesh data."""
import hashlib
import json
from pathlib import Path
import shutil
import sys
import bpy


def repair(row):
    from blender_animation_export import append_bone_animations,read_glb
    job=row['job'];directory=Path(row['directory']);source=directory/'final.glb'
    revision=hashlib.sha256(source.read_bytes()).hexdigest()[:12]
    before=directory/('material_final_'+revision+'.glb')
    if not before.exists():shutil.copy2(source,before)
    original=read_glb(before);extra={a['name']:a.get('extras') for a in original.json['animations']}
    blend=Path(job['glb']).with_suffix('.blend')
    bpy.ops.wm.open_mainfile(filepath=str(blend))
    arm=next(o for o in bpy.context.scene.objects if o.type=='ARMATURE')
    clips=json.loads((Path(job['output'])/'animation_manifest.json').read_text())['animations']
    target=directory/('posed_'+revision+'.glb');shutil.copy2(before,target)
    append_bone_animations(target,arm,clips,source_scale_compensation=True)
    result=read_glb(target)
    for a in result.json['animations']:
        if extra.get(a['name']) is not None:a['extras']=extra[a['name']]
    result.write(target)
    digest=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
    report={'id':row['id'],'beforeSha256':digest(before),'afterSha256':digest(target),
            'beforeFile':before.name,'afterFile':target.name,
            'sourceBlendSha256':digest(blend),'originalNodeCount':len(original.json['nodes']),
            'sourceBoneNames':[b.name for b in arm.pose.bones],
            'animationNames':[a['name'] for a in result.json['animations']],
            'reason':'Preserve evaluated source scale compensation in portable skin-joint TRS'}
    (directory/'pose_repair.json').write_text(json.dumps(report,indent=2)+'\n')
    print('POSE_REPAIRED',row['id'],flush=True)


if __name__=='__main__':
    sys.path.insert(0,str(Path(__file__).parent));args=sys.argv[sys.argv.index('--')+1:]
    catalog=json.loads(Path(args[0]).read_text());errors=[]
    for row in catalog['models']:
        try:repair(row)
        except Exception as error:
            import traceback;traceback.print_exc();errors.append({'id':row['id'],'error':str(error)})
    if errors:raise ValueError(errors)
