"""Expose source mesh-group alternatives through Attend's GLB form metadata."""
from __future__ import annotations

from .gltf.glb_io import read_glb

SWEETS = ("Strawberry","Blueberry","Heart","Star","Clover","Flower","Ribbon")
FLAVOR_MOUTHS = ("CreamMouth","PinkMouth","GreenMouth","BlueMouth","YellowMouth",
                 "WhiteMouth","CreamPinkMouth","BrownMouth","MultiColorMouth")
SWEET_LABELS = ("Strawberry Sweet","Berry Sweet","Love Sweet","Star Sweet",
                "Clover Sweet","Flower Sweet","Ribbon Sweet")


def annotate_alcremie(path,asset):
    if not asset.startswith("pm0925_") or asset[7:9] in ("81","82"):
        return False
    flavor=int(asset[7:9])-11
    if not 0<=flavor<len(FLAVOR_MOUTHS):
        raise ValueError("Unknown source Alcremie flavor")
    glb=read_glb(path)
    seen=set()
    for node in glb.json["nodes"]:
        if "mesh" not in node:
            continue
        name=node.get("name","")
        sweet=next((s for s in SWEETS if s in name),None)
        mouth=next((m for m in sorted(FLAVOR_MOUTHS,key=len,reverse=True) if m in name),None)
        forms=None
        if sweet:
            forms=[f"{SWEETS.index(sweet):02}"]
            seen.add(sweet)
        elif mouth and mouth!=FLAVOR_MOUTHS[flavor]:
            forms=["__hidden_source_alternative__"]
        if forms is not None:
            node.setdefault("extras",{}).setdefault("rae",{})["visibleForForms"]=forms
    if seen!=set(SWEETS):
        raise ValueError(f"Source Alcremie sweet groups incomplete: {set(SWEETS)-seen}")
    rae=glb.json["extras"]["rae"]
    options=[{"id":f"{i:02}","label":label} for i,label in enumerate(SWEET_LABELS)]
    rae["speciesVariants"]={"default":{"form":"00","shiny":False},"forms":options}
    appearance=rae["appearanceVariants"]
    appearance["default"]["form"]="00"
    appearance["axes"]=[a for a in appearance["axes"] if a["id"]!="form"]+[
        {"id":"form","label":"Sweet","default":"00","options":options}]
    rae["sourceSweetGroups"]=list(SWEETS)
    glb.write(path)
    return True
