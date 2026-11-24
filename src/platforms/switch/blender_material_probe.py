"""Inspect the pinned shader graph in a copied offline export job."""
import contextlib
import io
import json
from pathlib import Path
import sys

import bpy


def probe(job_path, output):
    prepared = json.loads(job_path.read_text())
    job = prepared["job"]
    deps = Path(job["dependencies"])
    sys.path[:0] = [str(deps / "python"), str(deps)]
    from pokemon_switch import PokemonSwitch
    PokemonSwitch.requests.get = lambda *a, **kw: (_ for _ in ()).throw(OSError("offline"))
    bpy.ops.wm.read_factory_settings(use_empty=True)
    with contextlib.redirect_stdout(io.StringIO()):
        PokemonSwitch.from_trmdlsv(job["raw"], job["modelFile"], False, False, True, False, False, False)
    records = []
    for material in bpy.data.materials:
        if not material.use_nodes:
            continue
        group = material.node_tree.nodes.get("Group")
        if not group:
            continue
        sockets = {}
        for socket in group.inputs:
            if not hasattr(socket, "default_value"):
                continue
            value = socket.default_value
            sockets[socket.name] = {"value": list(value) if hasattr(value, "__len__") else value,
                                    "linked": socket.is_linked}
        graph = group.node_tree
        output_nodes = [n for n in graph.nodes if n.type == "GROUP_OUTPUT"]
        connections = {s.name: [(l.from_node.name, l.from_socket.name, l.from_socket.identifier) for l in s.links]
                       for n in output_nodes for s in n.inputs}
        bake_graph = {}
        for link in next(n for n in graph.nodes if n.type == "GROUP_OUTPUT").inputs["BaseColorBake"].links:
            node = link.from_node
            bake_graph = {"node": node.name, "type": node.type,
                          "inputs": [{"name": s.name, "from": [(l.from_node.name,l.from_socket.name) for l in s.links],
                                      "value": list(s.default_value) if hasattr(getattr(s,"default_value",None),"__len__") else getattr(s,"default_value",None)}
                                     for s in node.inputs]}
            if node.type == "GROUP":
                bake_graph["nodes"] = [{"name": n.name,"type": n.type,
                                         "inputs": [{"name":s.name,"from":[(l.from_node.name,l.from_socket.name) for l in s.links]} for s in n.inputs]}
                                        for n in node.node_tree.nodes]
        records.append({"material": material.name, "inputs": sockets,
                        "outputs": [{"name":s.name,"links":[(l.to_node.name,l.to_socket.name) for l in s.links]} for s in group.outputs], "connections": connections, "bakeGraph": bake_graph, "rootGraph":[{"name":n.name,"type":n.type,"inputs":[{"name":s.name,"from":[(l.from_node.name,l.from_socket.name,l.from_socket.identifier) for l in s.links]} for s in n.inputs if s.is_linked]} for n in graph.nodes],
                        "graphDump": [{"name":g.name,"nodes":[{"name":n.name,"type":n.type,"operation":getattr(n,"operation",None),"blend":getattr(n,"blend_type",None),"inputs":[{"name":s.name,"from":[(l.from_node.name,l.from_socket.name,l.from_socket.identifier) for l in s.links],"value":list(s.default_value) if hasattr(getattr(s,"default_value",None),"__len__") else getattr(s,"default_value",None)} for s in n.inputs]} for n in g.nodes]} for g in bpy.data.node_groups if "Bake" in g.name or "Mask" in g.name or "Layer" in g.name],
                        "images": [{"node": n.name, "file": n.image.filepath,
                                    "size": list(n.image.size), "alphaMode": n.image.alpha_mode,
                                    "colorspace": n.image.colorspace_settings.name}
                                   for n in material.node_tree.nodes if n.type == "TEX_IMAGE" and n.image]})
    output.write_text(json.dumps(records, indent=2) + "\n")


if __name__ == "__main__":
    args = sys.argv[sys.argv.index("--") + 1:]
    probe(Path(args[0]), Path(args[1]))
