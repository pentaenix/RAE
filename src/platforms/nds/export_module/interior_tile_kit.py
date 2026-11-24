"""Export Gen 5 interior floor and wall geometry as Resort tile bundles."""
from __future__ import annotations

import json
import math
import re
import tempfile
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ....core.assets import Asset
from ..gltf.extract import extract_material_primitives, list_material_components
from ..gltf.glb_io import read_glb
from .tile_bundle import _material_motion_animations, write_tile_archive


@dataclass(frozen=True)
class InteriorTileCell:
    material: str
    role: str
    x: int
    y: int


def _slug(value: str, fallback: str = "tile") -> str:
    cleaned = re.sub(r"[^a-z0-9_-]+", "_", str(value).casefold()).strip("_")
    return cleaned or fallback


def _axis_cells(
    minimum: float,
    maximum: float,
    origin: float,
    tile_size: float,
    count: int,
) -> range:
    epsilon = max(1e-5, tile_size * 1e-5)
    if maximum - minimum <= epsilon:
        cell = math.floor(((minimum + maximum) * 0.5 - origin + epsilon) / tile_size)
        start = end = cell
    else:
        start = math.floor((minimum - origin + epsilon) / tile_size)
        end = math.ceil((maximum - origin - epsilon) / tile_size) - 1
    start = max(0, min(count - 1, start))
    end = max(0, min(count - 1, end))
    return range(start, end + 1) if start <= end else range(0)


def discover_interior_tile_cells(
    source_glb: str | Path,
    metadata: dict[str, Any],
    *,
    classify_material,
) -> tuple[InteriorTileCell, ...]:
    """Return every occupied grid cell for tile-compatible interior materials."""
    tile_size = float(metadata.get("tileSize") or 16.0)
    origin_x, origin_z = metadata.get("gridOrigin") or [0.0, 0.0]
    width, height = metadata.get("gridSize") or [0, 0]
    if tile_size <= 0.0 or int(width) < 1 or int(height) < 1:
        raise ValueError("Interior metadata requires a positive tileSize and gridSize.")

    allowed = {"floor", "wall", "entrance", "stairs", "window", "shadow"}
    cells: set[InteriorTileCell] = set()
    for material, components in list_material_components(Path(source_glb)).items():
        role = str(classify_material(material))
        if role not in allowed:
            continue
        for component in components:
            xs = _axis_cells(
                float(component.bounds_min[0]), float(component.bounds_max[0]),
                float(origin_x), tile_size, int(width))
            ys = _axis_cells(
                float(component.bounds_min[2]), float(component.bounds_max[2]),
                float(origin_z), tile_size, int(height))
            for y in ys:
                for x in xs:
                    cells.add(InteriorTileCell(material=material, role=role, x=x, y=y))
    return tuple(sorted(cells, key=lambda cell: (cell.role, cell.material.casefold(), cell.y, cell.x)))


def _has_triangles(path: Path) -> bool:
    document = read_glb(path).json
    accessors = document.get("accessors") or []
    for mesh in document.get("meshes") or []:
        for primitive in mesh.get("primitives") or []:
            accessor_index = primitive.get("indices")
            if isinstance(accessor_index, int) and 0 <= accessor_index < len(accessors):
                if int(accessors[accessor_index].get("count") or 0) >= 3:
                    return True
    return False


def _synthetic_asset(metadata: dict[str, Any]) -> Asset:
    source = metadata.get("source") or {}
    virtual_path = str(source.get("virtualPath") or "gen5/interior")
    map_index = int(source.get("mapFileIndex") or 0)
    return Asset(
        asset_id=f"gen5_interior_{map_index}",
        virtual_path=virtual_path,
        kind="model",
        magic="BMD0",
        extension=".nsbmd",
        data=b"",
        original_data=b"",
    )


def _suggested_tab(role: str) -> dict[str, str]:
    tabs = {
        "floor": ("interior_floors", "Interior Floors"),
        "wall": ("interior_walls", "Interior Walls"),
        "window": ("interior_walls", "Interior Walls"),
        "entrance": ("interior_entrances", "Interior Entrances"),
        "stairs": ("interior_stairs", "Interior Stairs"),
        "shadow": ("interior_shadows", "Interior Shadows"),
    }
    tab_id, name = tabs.get(role, ("interior_details", "Interior Details"))
    return {"id": tab_id, "name": name}


def export_gen5_interior_tile_kit(
    source_glb: str | Path,
    metadata: dict[str, Any],
    output_dir: str | Path,
    *,
    classify_material,
) -> tuple[Path, tuple[Path, ...]]:
    """Write a portable archive of tile-sized interior wall and floor bundles."""
    source = Path(source_glb)
    output = Path(output_dir)
    bundles_dir = output / "tiles"
    bundles_dir.mkdir(parents=True, exist_ok=True)
    tile_size = float(metadata.get("tileSize") or 16.0)
    origin_x, origin_z = metadata.get("gridOrigin") or [0.0, 0.0]
    floor_datum = float(metadata.get("floorDatum") or 0.0)
    asset = _synthetic_asset(metadata)
    records: list[dict[str, Any]] = []
    written: list[Path] = []

    for candidate in discover_interior_tile_cells(
        source, metadata, classify_material=classify_material):
        bounds = (
            float(origin_x) + candidate.x * tile_size,
            float(origin_z) + candidate.y * tile_size,
            float(origin_x) + (candidate.x + 1) * tile_size,
            float(origin_z) + (candidate.y + 1) * tile_size,
        )
        tile_id = (
            f"{candidate.role}_{_slug(candidate.material, 'material')}_"
            f"x{candidate.x:03d}_y{candidate.y:03d}"
        )
        with tempfile.TemporaryDirectory(prefix="rae_interior_tile_") as temp_name:
            temp = Path(temp_name)
            model_path = temp / "model.glb"
            try:
                extract_material_primitives(
                    source,
                    model_path,
                    [candidate.material],
                    recenter=True,
                    spatial_tile_bounds=bounds,
                    origin_y=floor_datum,
                    origin_xz=(
                        float(origin_x) + (candidate.x + 0.5) * tile_size,
                        float(origin_z) + (candidate.y + 0.5) * tile_size,
                    ),
                )
            except ValueError:
                continue
            if not _has_triangles(model_path):
                continue
            staging = temp / "bundle"
            staging.mkdir()
            animations = _material_motion_animations(model_path, staging)
            bundle_path = bundles_dir / f"{tile_id}.tile"
            blocked = candidate.role in {"wall", "window"}
            write_tile_archive(
                bundle_path,
                model_glb=model_path,
                asset=asset,
                animations=animations,
                staging=staging,
                selected_materials=[candidate.material],
                name_override=f"Interior {candidate.role}: {candidate.material} ({candidate.x}, {candidate.y})",
                source_details={
                    "profile": "gen5_interior_tiles",
                    "mapFileIndex": int((metadata.get("source") or {}).get("mapFileIndex") or 0),
                    "sourceCell": [candidate.x, candidate.y],
                    "spatialBounds": list(bounds),
                },
                footprint=(1, 1),
                default_tags=["interior", f"interior.{candidate.role}"],
                default_properties={
                    "interior.role": candidate.role,
                    "interior.sourceMaterial": candidate.material,
                },
                default_collision={
                    "mode": "footprint" if blocked else "none",
                    "autoApply": blocked,
                    "clearOnErase": blocked,
                },
            )
        written.append(bundle_path)
        records.append({
            "id": tile_id,
            "role": candidate.role,
            "sourceMaterial": candidate.material,
            "bundle": f"tiles/{bundle_path.name}",
            "sourceCell": [candidate.x, candidate.y],
            "footprint": [1, 1],
            "collisionHint": "blocked" if blocked else "walkable",
            "suggestedTab": _suggested_tab(candidate.role),
        })

    if not records:
        raise ValueError("Interior shell contains no tile-sized floor, wall, entrance, stair, window, or shadow geometry.")
    manifest = {
        "format": "rae.gen5InteriorTileKit",
        "version": 1,
        "source": metadata.get("source") or {},
        "tileSize": tile_size,
        "gridOrigin": metadata.get("gridOrigin") or [0.0, 0.0],
        "gridSize": metadata.get("gridSize") or [0, 0],
        "floorDatum": floor_datum,
        "componentPolicy": "grid-cell",
        "suggestedTabs": list({
            tab["id"]: tab
            for tab in (_suggested_tab(record["role"]) for record in records)
        }.values()),
        "tiles": records,
    }
    manifest_path = output / "interior-tile-kit.json"
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    archive_path = output / "interior-tile-kit.zip"
    with zipfile.ZipFile(archive_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.write(manifest_path, "interior-tile-kit.json")
        for path in written:
            archive.write(path, f"tiles/{path.name}")
    return manifest_path, tuple(written)
