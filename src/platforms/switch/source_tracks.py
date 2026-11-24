"""Read pinned Game Freak track objects without importing Blender."""
from bisect import bisect_right


def packed_bools(data, count):
    if not len(data):
        return [False] * count
    return [bool(int(data[min(i, len(data)*8-1) // 8]) &
                 (1 << (min(i, len(data)*8-1) % 8))) for i in range(count)]


def sample_keys(frames, values, frame, *, step=False):
    if not len(values):
        raise ValueError("Empty source animation track")
    index = max(0, bisect_right(frames, frame) - 1)
    if index >= len(values) - 1 or step or frame <= frames[0]:
        return values[min(index, len(values) - 1)]
    end = frames[index + 1]
    amount = (frame - frames[index]) / max(1e-8, end - frames[index])
    return values[index] + (values[index + 1] - values[index]) * amount


def dense_track(track, count, *, boolean=False):
    if track is None:
        return []
    data = vars(track)
    if "bool" in data:
        return [bool(data["bool"])] * count
    if "float" in data:
        value = data["float"]
    elif "value" in data:
        value = data["value"]
    elif "byte" in data:
        size = len(data.get("frames", [])) if "frames" in data else count
        payload = data["byte"]
        if not hasattr(payload, "__len__"):
            payload = [int(payload)] * ((size + 7) // 8)
        value = packed_bools(payload, size) if boolean else payload
    else:
        raise ValueError("Unsupported source track: " + type(track).__name__)
    if not hasattr(value, "__len__"):
        return [bool(value) if boolean else float(value)] * count
    frames = data.get("frames", range(len(value)))
    return [bool(sample_keys(frames, value, frame, step=True)) if boolean else
            float(sample_keys(frames, value, frame)) for frame in range(count)]
