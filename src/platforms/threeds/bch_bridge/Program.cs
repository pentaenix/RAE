// Decode ORAS BCH/GF1 with the pinned local SPICA library. No renderer or GPU.
using SPICA.Formats.CtrH3D;
using SPICA.Formats.CtrH3D.Animation;
using SPICA.Formats.CtrH3D.Model;
using SPICA.Formats.CtrH3D.Model.Mesh;
using SPICA.Formats.GFL;
using SPICA.PICA.Converters;
using SPICA.PICA.Commands;
using SixLabors.ImageSharp;
using System.Numerics;
using System.Text.Json;

static float[] V3(Vector3 v) => new[]{v.X,v.Y,v.Z};
static float[] P3(Vector4 v) => new[]{v.X,v.Y,v.Z};
static float[] V2(Vector4 v) => new[]{v.X,v.Y};
static float[] Sample(H3DFloatKeyFrameGroup group,int frames) => !group.Exists
    ? Array.Empty<float>() : Enumerable.Range(0,group.KeyFrames.Count==1?1:frames+1)
        .Select(i=>group.GetFrameValue(i)).ToArray();

static object DescribeMesh(H3DModel model,H3DMesh mesh,int number) {
    var all=VerticesConverter.GetVertices(mesh);
    string name=model.MeshNodesTree!=null && mesh.NodeIndex<model.MeshNodesTree.Count
        ? model.MeshNodesTree.Find(mesh.NodeIndex) : "mesh"+number;
    return new {name,submeshes=mesh.SubMeshes.Select(sub=> {
        var used=sub.Indices.Distinct().OrderBy(i=>i).ToArray();
        var mapping=used.Select((old,index)=>(old,index)).ToDictionary(x=>x.old,x=>x.index);
        var verts=used.Select(i=>all[i]).ToArray();
        return new { material_name=model.Materials[mesh.MaterialIndex].Name,
            positions=verts.Select(v=>P3(v.Position)).ToArray(),
            normals=verts.Select(v=>P3(v.Normal)).ToArray(),
            uvs=verts.Select(v=>V2(v.TexCoord0)).ToArray(),
            colors=mesh.Attributes.Any(a=>a.Name==PICAAttributeName.Color) || mesh.FixedAttributes.Any(a=>a.Name==PICAAttributeName.Color)
                ? verts.Select(v=>new[]{v.Color.X,v.Color.Y,v.Color.Z,v.Color.W}).ToArray() : Array.Empty<float[]>(),
            indices=sub.Indices.Select(i=>mapping[i]).ToArray(),
            bone_table=Array.Empty<int>(),
            joints=verts.Select(v=>Enumerable.Range(0,4).Select(i=>
                (sub.Skinning==H3DSubMeshSkinning.Smooth?v.Weights[i]:i==0?1:0)>0
                    ? (int)sub.BoneIndices[Math.Max(0,v.Indices[i])] : 0).ToArray()).ToArray(),
            weights=verts.Select(v=>sub.Skinning==H3DSubMeshSkinning.Smooth
                ? Enumerable.Range(0,4).Select(i=>v.Weights[i]).ToArray() : new[]{1f,0,0,0}).ToArray()};
    }).ToArray()};
}

static object[] DescribeTextures(H3D scene,string output,string color) {
    string directory=Path.Combine(output,color);Directory.CreateDirectory(directory);
    return scene.Textures.Select((texture,index)=> {
        string path=Path.Combine(directory,$"tex{index:000}.png");
        using var image=texture.ToBitmap();image.SaveAsPng(path);
        return (object)new {name=texture.Name,width=image.Width,height=image.Height,path};
    }).ToArray();
}

static object[] DescribeMotions(string path,H3DModel model,int slot) {
    using var input=File.OpenRead(path);
    return new GF1MotionPack(input).Select(motion=> {
        H3DAnimation animation=motion.ToH3DSkeletalAnimation(model.Skeleton);
        return (object)new {name=$"slot{slot}_{motion.Index:00}",frames=(int)animation.FramesCount,
            bones=animation.Elements.Select(element=> {
                if(element.Content is not H3DAnimTransform t)
                    throw new InvalidDataException("Unsupported ORAS bone curve: "+element.PrimitiveType);
                return new {name=element.Name,channels=new[]{t.ScaleX,t.ScaleY,t.ScaleZ,
                    t.RotationX,t.RotationY,t.RotationZ,t.TranslationX,t.TranslationY,t.TranslationZ}
                    .Select(g=>Sample(g,(int)animation.FramesCount)).ToArray()};
            }).ToArray()};
    }).ToArray();
}

try {
    using var job=JsonDocument.Parse(File.ReadAllText(args[0]));var j=job.RootElement;
    string PathFor(string key)=>j.GetProperty(key).GetString()!;
    string output=PathFor("output");Directory.CreateDirectory(output);
    H3D scene=H3D.Open(File.ReadAllBytes(PathFor("model")));
    if(scene.Models.Count!=1)throw new InvalidDataException("Expected one high-detail BCH model");
    var model=scene.Models[0];
    var decoded=new { name=model.Name,
        bones=model.Skeleton.Select(b=>new {name=b.Name,parent=b.ParentIndex<0?"":model.Skeleton[b.ParentIndex].Name,
            flags=0,scale=V3(b.Scale),rotation=V3(b.Rotation),translation=V3(b.Translation)}).ToArray(),
        materials=model.Materials.Select(m=>new {name=m.Name,
            render_state=new {color_operation=m.MaterialParams.ColorOperation.ToUInt32(),
                blend_function=m.MaterialParams.BlendFunction.ToUInt32(),alpha_test=m.MaterialParams.AlphaTest.ToUInt32(),
                depth_color_mask=m.MaterialParams.DepthColorMask.ToUInt32(),cull_mode=(int)m.MaterialParams.FaceCulling},
            texture_names=new[]{m.Texture0Name,m.Texture1Name,m.Texture2Name},
            texture_units=m.MaterialParams.TextureCoords.Select((c,i)=>new {
                name=new[]{m.Texture0Name,m.Texture1Name,m.Texture2Name}[i],unit_index=i,
                scale=new[]{c.Scale.X,c.Scale.Y},rotation=c.Rotation,
                translation=new[]{c.Translation.X,c.Translation.Y},mapping_type=(int)c.MappingType,
                wrap_u=(int)m.TextureMappers[i].WrapU,wrap_v=(int)m.TextureMappers[i].WrapV}).ToArray()}).ToArray(),
        meshes=model.Meshes.Select((m,i)=>DescribeMesh(model,m,i)).ToArray(),
        normal=DescribeTextures(H3D.Open(File.ReadAllBytes(PathFor("normal"))),output,"normal"),
        rare=DescribeTextures(H3D.Open(File.ReadAllBytes(PathFor("rare"))),output,"rare"),
        animations=DescribeMotions(PathFor("battle"),model,4).Concat(DescribeMotions(PathFor("care"),model,5)).ToArray()};
    File.WriteAllText(Path.Combine(output,"decoded.json"),JsonSerializer.Serialize(decoded));
    Console.WriteLine($"Decoded {model.Name}: {model.Skeleton.Count} bones, {decoded.animations.Length} clips");
    return 0;
} catch(Exception ex) {Console.Error.WriteLine(ex);return 1;}
