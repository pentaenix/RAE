"""Read SV TRACM mesh switches and material scalar/vector curves.

TRACM is independent of the skeletal TRANM container. Mesh entries store a
visibility-controller boolean union and optional material parameter curves.
"""
import struct
from bisect import bisect_right

from . import flatbuf as fb
from .source_tracks import packed_bools


def _float(data, field, default=0.):
    return struct.unpack_from("<f", data, field)[0] if field is not None else default


def _vector(data, field, code):
    if field is None:
        return []
    offset = fb.vector_offset(data, field)
    count = fb.vector_len(data, offset)
    size = struct.calcsize(code)
    if count > len(data) // size or offset + 4 + count * size > len(data):
        raise ValueError("Invalid TRACM vector bounds")
    return list(struct.unpack_from("<" + str(count) + code, data, offset + 4))


def _curve(data, field, count):
    curve = fb.child_table(data, field)
    if curve is None:
        return []
    keys = fb.read_table_vector(data, curve.get(0))
    points = [(_float(data, key.get(0)), _float(data, key.get(1)),
               _float(data, key.get(2)), _float(data, key.get(3)),
               fb.u8(data, key.get(4)) if key.get(4) else 0) for key in keys]
    if not points:
        return []
    times = [p[0] for p in points]
    result = []
    for frame in range(count):
        index = max(0, bisect_right(times, frame) - 1)
        a = points[index]
        if index == len(points) - 1 or a[4] == 1 or frame <= times[0]:
            result.append(a[1])
            continue
        b = points[index + 1]
        duration = max(1e-8, b[0] - a[0])
        t = (frame - a[0]) / duration
        if a[3] or b[2]:
            value = (2*t**3-3*t*t+1)*a[1] + (t**3-2*t*t+t)*a[3]*duration
            value += (-2*t**3+3*t*t)*b[1] + (t**3-t*t)*b[2]*duration
        else:
            value = a[1] + (b[1] - a[1]) * t
        result.append(value)
    return result


def _visibility(data, field, count):
    controller = fb.child_table(data, field)
    union = fb.child_table(data, controller.get(2)) if controller else None
    if union is None:
        return None
    kind = fb.u8(data, union.get(0)) if union.get(0) else 0
    value = fb.child_table(data, union.get(1))
    if value is None:
        return None
    if kind == 1:
        return [bool(fb.u8(data, value.get(0))) if value.get(0) else False] * count
    if kind == 2:
        packed = _vector(data, value.get(0), "B")
        return packed_bools(packed, count)
    if kind in (3, 4):
        frames = _vector(data, value.get(0), "H" if kind == 3 else "B")
        packed = _vector(data, value.get(1), "B")
        values = [bool(packed[i//8] & (1 << (i % 8))) for i in range(len(frames))]
        return [values[max(0, bisect_right(frames, frame)-1)] for frame in range(count)]
    raise ValueError("Unsupported TRACM visibility type: " + str(kind))


def read_tracm(data):
    root = fb.table_fields(data, fb.root_offset(data))
    info = fb.child_table(data, root.get(0))
    count = fb.u32(data, info.get(1)) if info and info.get(1) else 1
    fps = fb.u32(data, info.get(2)) if info and info.get(2) else 60
    if not 0 < count <= 100000 or not 0 < fps <= 1000:
        raise ValueError("Invalid TRACM animation timing")
    result = {"frames": count, "fps": fps, "visibility": {}, "materials": {}}
    for entry in fb.read_table_vector(data, root.get(1)):
        name = fb.read_string(data, entry.get(0))
        visible = _visibility(data, entry.get(5), count)
        if visible is not None:
            result["visibility"][name] = visible
        collection = fb.child_table(data, entry.get(4))
        if collection is None:
            continue
        for material in fb.read_table_vector(data, collection.get(2)):
            params = result["materials"].setdefault(fb.read_string(data, material.get(0)), {})
            for track in fb.read_table_vector(data, material.get(1)):
                params[fb.read_string(data, track.get(0))] = _curve(data, track.get(1), count)
            for track in fb.read_table_vector(data, material.get(2)):
                vector = fb.child_table(data, track.get(1))
                channels = [_curve(data, vector.get(i), count) for i in range(4)]
                if all(channels):
                    params[fb.read_string(data, track.get(0))] = list(map(list, zip(*channels)))
    return result
