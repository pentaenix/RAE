"""Read embedded TRMMT color-form curves, including normal and rare palettes.

TRMMT reference: pkNX MultiMaterialTable.fbs. Embedded TRACM tracks carry
per-mesh material RGBA curves; integer form selectors are sampled exactly.
"""
from __future__ import annotations

import struct

from . import flatbuf as fb


def _curve(data, table, frame):
    keys = fb.read_table_vector(data, table.get(0))
    values = [(struct.unpack_from("<f",data,k.get(0))[0] if k.get(0) else 0.,
               struct.unpack_from("<f",data,k.get(1))[0] if k.get(1) else 0.) for k in keys]
    if not values or any(a[0]>b[0] for a,b in zip(values,values[1:])):
        raise ValueError("Invalid embedded material curve")
    # Forms are authored at exact integer frames. Held channels may omit keys.
    return next((value for time,value in reversed(values) if time<=frame), values[0][1])


def embedded_color_tracks(data: bytes, frame: int) -> list[dict]:
    root = fb.table_fields(data,fb.root_offset(data))
    result = []
    for track in fb.read_table_vector(data,root.get(1)):
        mesh = fb.read_string(data,track.get(0))
        holder = fb.child_table(data,track.get(4))
        if holder is None:
            continue
        for material in fb.read_table_vector(data,holder.get(2)):
            name = fb.read_string(data,material.get(0))
            for parameter in fb.read_table_vector(data,material.get(2)):
                layer = fb.read_string(data,parameter.get(0))
                rgba = fb.child_table(data,parameter.get(1))
                if rgba is None or len(rgba.offsets)!=4:
                    raise ValueError("Unsupported embedded color parameter")
                color = [_curve(data,fb.child_table(data,p),frame) for p in rgba.offsets]
                result.append({"mesh":mesh,"material":name,"parameter":layer,"value":color})
    return result


def read_cosmetics(data: bytes) -> dict:
    root = fb.table_fields(data,fb.root_offset(data))
    result = {}
    for material in fb.read_table_vector(data,root.get(2)):
        color = fb.read_string(data,material.get(0))
        for prop in fb.read_table_vector(data,material.get(3)):
            name = fb.read_string(data,prop.get(0))
            maximum = fb.u32(data,prop.get(3)) if prop.get(3) else 0
            embedded = fb.child_table(data,prop.get(4))
            if maximum == 0 or embedded is None:
                continue
            if maximum>255:
                raise ValueError("Cosmetic selector exceeds 256 forms")
            offset = fb.vector_offset(data,embedded.get(0))
            payload = data[offset+4:offset+4+fb.vector_len(data,offset)]
            forms = [embedded_color_tracks(payload,frame) for frame in range(maximum+1)]
            if any(not form for form in forms):
                raise ValueError("Cosmetic form has no material values")
            result.setdefault(name,{})[color] = forms
    return result
