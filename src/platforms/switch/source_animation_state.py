"""Portable source visibility/material state, independent of skeletal conversion."""
from pathlib import Path
import sys

from .source_tracks import dense_track
from .sv_material_animation import read_tracm


def read_animation_state(path: Path, dependencies: Path):
    if path.suffix == ".tracm":
        return read_tracm(path.read_bytes())
    for folder in (dependencies / "python", dependencies / "pokemon_switch"):
        if str(folder) not in sys.path:
            sys.path.insert(0, str(folder))
    from GFLib.Anim.Animation import Animation
    from GFLib.Anim.SkinTrack import SkinTrackT
    from GFLib.Anim.ShaderEntry import ShaderEntryT
    animation = Animation.GetRootAs(bytearray(path.read_bytes()))
    info = animation.Info()
    count, fps = info.KeyFrames(), info.FrameRate()
    result = {"frames": count, "fps": fps, "visibility": {}, "materials": {}}
    visibility = animation.Visibility()
    if visibility:
        for index in range(visibility.TracksLength()):
            track = SkinTrackT.InitFromObj(visibility.Tracks(index))
            result["visibility"][track.name.decode()] = dense_track(track.values, count, boolean=True)
    materials = animation.Material()
    if materials:
        for index in range(materials.TracksLength()):
            track = materials.Tracks(index)
            params = result["materials"].setdefault(track.Name().decode(), {})
            for i in range(track.ValuesLength()):
                source = track.Values(i)
                name = source.Name().decode()
                value = ShaderEntryT.InitFromObj(source)
                params[name] = dense_track(value.value, count)
    return result
