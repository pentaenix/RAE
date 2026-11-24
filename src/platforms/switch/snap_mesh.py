"""Static geometry and UV streams from SSBH Mesh 1.10."""
from __future__ import annotations

import struct
from dataclasses import dataclass

import numpy as np

# SSBH relative arrays and records, as documented by ultimate-research/ssbh_lib.
_OBJECT_SIZE = 208
_ATTRIBUTE_SIZE = 48


@dataclass(frozen=True, slots=True)
class SnapMesh:
    name: str
    subindex: int
    positions: np.ndarray
    normals: np.ndarray
    uv: np.ndarray
    lightmap_uv: np.ndarray | None
    layer_mask: np.ndarray | None
    indices: np.ndarray


def _array(data: bytes, offset: int, item_size: int) -> tuple[int, int]:
    relative, count = struct.unpack_from("<QQ", data, offset)
    start = offset + relative
    if start + count * item_size > len(data):
        raise ValueError("Snap mesh array extends beyond its payload")
    return start, count


def _attribute(data, obj, attr, buffers, buffer_count, vertex_count, components) -> np.ndarray:
    _, encoding, slot, attribute_offset = attr
    if encoding != {2: 7, 3: 0, 4: 4}[components] or slot >= min(buffer_count, 4):
        raise ValueError("Unsupported Snap vertex attribute format")
    buffer_start, buffer_size = _array(data, buffers + slot * 16, 1)
    offset = struct.unpack_from("<I", data, obj + 36 + slot * 4)[0] + attribute_offset
    stride = struct.unpack_from("<I", data, obj + 52 + slot * 4)[0]
    width = components * 4
    if stride < width or offset + (vertex_count - 1) * stride + width > buffer_size:
        raise ValueError("Snap vertex attribute exceeds its buffer")
    values = np.ndarray((vertex_count, components), dtype="<f4", buffer=data,
                        offset=buffer_start + offset, strides=(stride, 4))
    if not np.isfinite(values).all():
        raise ValueError("Snap mesh contains invalid vertex data")
    return values


def read_static_meshes(data: bytes) -> list[SnapMesh]:
    if len(data) < 224 or data[:4] != b"HBSS" or data[16:24] != b"HSEM\x01\x00\x0a\x00":
        raise ValueError("Expected a Snap SSBH Mesh 1.10 payload")
    objects, object_count = _array(data, 136, _OBJECT_SIZE)
    buffers, buffer_count = _array(data, 176, 16)
    index_buffer, index_size = _array(data, 192, 1)
    meshes = []
    for obj in range(objects, objects + object_count * _OBJECT_SIZE, _OBJECT_SIZE):
        name_offset, subindex = struct.unpack_from("<QQ", data, obj)
        start = obj + name_offset
        name = data[start:data.index(b"\0", start)].decode("ascii")
        vertices, index_count = struct.unpack_from("<II", data, obj + 24)
        if not vertices or not index_count:
            continue
        index_offset, _, index_type, skinned = struct.unpack_from("<4I", data, obj + 68)
        if skinned or index_type not in (0, 1) or index_count % 3:
            raise ValueError(f"Unsupported Snap triangle mesh: {name}")
        index_dtype = np.dtype("<u2" if index_type == 0 else "<u4")
        if index_offset + index_count * index_dtype.itemsize > index_size:
            raise ValueError(f"Snap index range exceeds its buffer: {name}")
        indices = np.frombuffer(data, dtype=index_dtype, count=index_count, offset=index_buffer + index_offset)
        if int(indices.max()) >= vertices:
            raise ValueError(f"Snap index exceeds its vertex count: {name}")
        attributes, attr_count = _array(data, obj + 192, _ATTRIBUTE_SIZE)
        attributes_by_slot = {}
        for offset in range(attributes, attributes + attr_count * _ATTRIBUTE_SIZE, _ATTRIBUTE_SIZE):
            attr = struct.unpack_from("<4I", data, offset)
            (channel,) = struct.unpack_from("<Q", data, offset + 16)
            attributes_by_slot[attr[0], channel] = attr
        streams = []
        for usage, channel, components in ((0, 0, 3), (1, 0, 3), (4, 0, 2)):
            attr = attributes_by_slot.get((usage, channel))
            if attr is None:
                raise ValueError(f"Snap mesh lacks vertex attribute {usage}:{channel}: {name}")
            streams.append(_attribute(data, obj, attr, buffers, buffer_count, vertices, components))
        lightmap = attributes_by_slot.get((4, 1))
        lightmap_uv = _attribute(data, obj, lightmap, buffers, buffer_count, vertices, 2) if lightmap else None
        colors = attributes_by_slot.get((5, 0))
        layer_mask = None
        if colors and colors[1] == 4:
            rgba = _attribute(data, obj, colors, buffers, buffer_count, vertices, 4)
            # Use the painted alpha as the primary layer weight in the preview.
            layer_mask = 1 - np.clip(rgba[:, 3], 0, 1)
        meshes.append(SnapMesh(name, subindex, *streams, lightmap_uv, layer_mask, indices))
    if not meshes:
        raise ValueError("Snap mesh has no static triangles")
    return meshes
