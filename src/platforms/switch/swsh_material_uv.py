"""Original GFBMDL static sampler transforms, independent of Blender."""


def color_uv_transform(values, *, layer=False):
    prefix='Layer1' if layer else 'Color'
    scale=tuple(float(values.get(prefix+'UVScale'+axis,1)) for axis in ('U','V'))
    offset=tuple(scale[i]*float(values.get(prefix+'UVTranslate'+axis,0))+
                 float(values.get(prefix+'Base'+axis,0)) for i,axis in enumerate(('U','V')))
    return scale,offset


def blender_color_uv_transform(values, *, layer=False):
    """Convert the source top-left sampler transform to Blender's bottom-left V."""
    scale,offset=color_uv_transform(values,layer=layer)
    return scale,(offset[0],1-scale[1]-offset[1])
