# Gen 5 interior export

RAE treats an interior as exact Nitro terrain geometry plus authoring metadata. It does not flatten, redraw, or hand-assemble the source model.

For a carved Black 2 map model, open **Map Objects → Export…**. When the terrain contains both floor and wall materials, two additional actions appear:

- **Interior shell + grid metadata** writes `map_NNNN_interior.glb` and `map_NNNN_interior.interior.json`.
- **Interior tile kit** writes `tile-kit/interior-tile-kit.zip`, its manifest, and one portable `.tile` bundle for every occupied floor, wall, entrance, stair, window, or shadow grid cell.

The sidecar records the ROM path/index, AreaData index, exact source bounds, grid origin, walkable/blocked masks, inferred floor-height step, per-cell heights, material roles, and entrance/halo coordinates. The same object is embedded at `extras.rae.interiorMap` in the GLB.

Interior tiles retain their clipped source geometry, UVs, embedded textures, and applicable material animation metadata. Each bundle is centered on its source cell, tagged `interior` and `interior.<role>`, and records `interior.role`, source material, source cell, collision defaults, and a suggested tile-pack tab. Floors are routed to **Interior Floors**, walls and windows to **Interior Walls**, with separate entrance, stair, shadow, and detail tabs where present. Wall and window bundles apply footprint collision automatically. `interior-tile-kit.json` preserves the source grid, suggested tabs, and provenance, and the ZIP is the editor import artifact.

The earlier `rae.gen5InteriorKit` material-group archive remains readable by Map Studio for existing exports. New exports use `rae.gen5InteriorTileKit` so walls and floors are paintable RTPKS tiles rather than room-sized prop models.

## Vertically overlapping floors

Pokémon Resort's OWMAP terrain is a 2D grid with one gameplay height per cell. RAE records every vertically ambiguous cell in `ambiguousFloorCells` and chooses the highest sampled surface for `heightMask`. A stacked floor is therefore preserved visually in the shell but must be split into separate Resort maps/spaces before its lower and upper levels can both be playable.
