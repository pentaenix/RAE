# Nintendo Switch platform

Reads retail **NSP/XCI** dumps: decrypts NCAs, walks RomFS, unpacks the
Trinity ``data.trpfd`` / ``data.trpfs`` archive, and exports models as GLB.

## Requirements

| File | Purpose |
|------|---------|
| ``prod.keys`` | AES keys from your console (Lockpick_RCM). Place next to the ROM or in ``~/.switch/``. |
| ``oo2core_*.dll`` / ``liboo2core.dylib`` | Oodle decompressor for packed meshes/textures. Set ``RAE_SWITCH_OODLE_DLL`` to its path. |

Without ``prod.keys`` the ROM scans as a single locked row. Without Oodle,
models/textures inside TRPAKs cannot be decoded (metadata-only TRMDL reads work).

## Status

| Layer | State |
|-------|-------|
| NCA decrypt + RomFS | Done |
| TRPFS / TRPFD / TRPAK unpack | Done |
| Name-hash cache (loaded on demand) | Done — ``roms/sv_hashes_inside_trpak.txt`` |
| Scan: Pokémon models/textures/anims, maps, characters, icons | Done |
| TRMDL + TRMSH + TRMBF + TRSKL → GLB | Done (needs Oodle at runtime) |
| BNTX base-mip PNG decoding | Done for ordinary 2D RGBA/R/RG and unsigned BC1–5/7 textures |
| Animated, textured Pokémon GLB | Pilot CLI below (Blender dependency); not the UI's geometry-only GLB action |
| Material animation / effects | Raw preservation only; TRACM/TRAEF conversion still pending |

## New Pokémon Snap course previews

Open the ROM in RAE and search for **Lental Seafloor**. Select **Undersea**
for the main course or **Illumina Spot** for the separate encounter area.
Click the preview and drag to look. Use **WASD** to swim, **Q/E** to
descend/ascend, **Shift** to move faster, and **R** to return to the start.

The previews show the course geometry and its ROM textures through Qt
WebEngine. The camera has no collision. Water and lighting are approximated,
and Undersea's larger textures are reduced for the preview. The course rows
have no export action.

## Single-Pokémon animated pilot (Scarlet/Violet)

The first verified target is **Sprigatito, National Dex 906**, whose internal
asset ID is **`pm1010_00_00`**. Internal IDs are not National Dex IDs;
`pm0906` is not Sprigatito. This command only accepts Gen 8/9 species numbers
and writes a new output directory. It never installs or replaces Resort assets.
Sword/Shield's GFPAK/GFBMDL batch is described below.

One-time local dependencies (Blender 5.1.2 was used for the pilot):

```bash
git clone https://github.com/ChicoEevee/Pokemon-Switch-Model-Importer-Blender.git .cache/switch-tools/pokemon_switch
git -C .cache/switch-tools/pokemon_switch checkout bb597581916c7407385afb5461efe4d2ae2f38f9
.venv/bin/python -m pip install --target .cache/switch-tools/python --no-deps flatbuffers==25.9.23
.venv/bin/python -m pip install 'texture2ddecoder>=1.0.4'
```

Run from the RAE root, with your own ROM and keys:

```bash
.venv/bin/python -m rae.platforms.switch.pokemon_export \
  'roms/Pokemon Scarlet.nsp' exports/switch_pokemon/pm0906_00_Sprigatito \
  --asset-id pm1010_00_00 --species 906 --name Sprigatito
```

Use `--blender /absolute/path/to/Blender` or `RAE_BLENDER` if needed. The
importer and its shader stay in the ignored cache. Conversion runs offline
with factory Blender settings, without registering an add-on or changing
Blender preferences. Check `conversion.log` if Blender fails.

Output contains:

- `pm0906_00_Sprigatito.glb`: one skin, four meshes, embedded baked base colors,
  and all 50 source skeletal clips (idle, walking/running, rest/sleep,
  eating, attacks, reactions, eye and mouth poses).
- Matching editable `.blend`, PNG bake textures, and animation manifest.
- `raw/`: the exact 171 decoded source files, including 50 TRACM files and
  29 TRAEF files; `raw_manifest.json` records file hashes and source asset IDs.
- `export_report.json`: counts after checking that no skeletal clip or skin
  weights were lost. GLB materials and document carry `extras.rae.platform`.

Colors are baked into ordinary glTF materials with new UVs so consumers
do not need the game's layered shader. The game lighting, PBR detail, animated
UV/material parameters, and effects are not reproduced. Skeletal eye/mouth
clips are included; TRACM facial/material motion remains raw. Retain the source
bundle for later improvements. A successful GLB export does not configure
Resort's semantic animation adapter or its model-provider discovery.

When expanding, keep Resort's Gen 1–7 provider and assets, and add a separate
Gen 8/9 provider using explicit National Dex → source asset mappings. Do not
batch-replace legacy species just because they also appear in Switch games.

The external importer is maintained by
[ChicoEevee and contributors](https://github.com/ChicoEevee/Pokemon-Switch-Model-Importer-Blender),
with animation import from
[Shararamosh](https://github.com/Shararamosh/io_scene_gfbanm).
RAE's ROM extraction, BNTX decode, orchestration and GLB metadata remain local
to this Switch island. No game assets, keys, or third-party importer sources
are checked into the repository.

## Gen 9-only animated batch

The batch uses an explicit National Dex/internal-ID catalog, excluding older
species and Hisui's Gen 8 additions. It inventories the actual archive before
conversion; missing update/DLC species are reported instead of assumed present.
Internal IDs follow [RTB's model list](https://archive.vg-resource.com/thread-25872.html).

Install the optional Khronos validator in the local tool cache:

```bash
npm install --prefix .cache/switch-tools/gltf-validator gltf-validator@2.0.0-dev.3.10
.venv/bin/python -m rae.platforms.switch.batch_gen9 \
  'roms/Pokemon Scarlet.nsp' exports/switch_gen9 --workers 3
```

`inventory.json` lists available forms and missing species. `progress.json` is
updated atomically, and `batch_report.json` records every result. Each form keeps
the source bundle, editable Blender scene, embedded animated GLB, export counts,
and Khronos validation report. Re-running checks hashes and resumes completed
forms. `--inventory-only` skips conversion; `--only 906 911` repairs selected
species while retaining the complete inventory/progress report.

The Blender worker exports static geometry once, then samples every evaluated
bone pose once per source frame using Blender's rest-bone transform convention.
Constant tracks retain both endpoints so static clips keep their duration.
Descendants of prop bones animated to tiny scales are reparented to a stable
ancestor with evaluated pose tracks. This preserves skin binds and avoids
unstable float32 scale-compensation chains, including Floragato's hidden prop.
`animationWriter: "blender_actions"` in a worker job selects Blender's slower
general action exporter as a reference/fallback. No material or effect animation
is synthesized. Conversion remains offline and inside the Switch island.

## Base games, updates, Sword/Shield and appearances

`SwitchRom` supplements its private, in-memory key set with common NSP tickets.
`PatchedSwitchRom(base, update)` validates the matching application ID and reads
the BKTR relocation overlay with its CTR-Ex subsection counters. Neither ROM nor
the console key files are changed. It supports concurrent random reads without
writing a full decrypted game image. Personalized RSA tickets still require an
explicit console-derived title key. Update model data also supplies the DLC
models; the tiny DLC license NSPs do not contain the model archives.

```sh
.venv/bin/python -m pip install -e '.[switch]'
.venv/bin/python -m rae.platforms.switch.batch_gen9 \
  'roms/Pokemon Scarlet.nsp' exports/switch_complete/scarlet \
  --update 'roms/Pokemon Scarlet (Update).nsp' --include-shiny --workers 3
.venv/bin/python -m rae.platforms.switch.batch_swsh \
  /path/to/Sword-base.nsp /path/to/Sword-update.nsp \
  exports/switch_complete/sword --workers 3
```

The Sword catalog admits Gen 8 species, Meltan/Melmetal, Galarian forms,
Gigantamax forms and World Cap Pikachu. It excludes ordinary older models so the
preferred Gen 7 assets keep their place. `complete_catalog.py` also identifies
Hisuian/Paldean and Origin forms in SV; an explicit JSON catalog can be passed
with `batch_gen9 --catalog`. Internal model IDs always map to National Dex IDs
before export. Source pack/file hashes remain in each raw manifest.

Normal and rare models are imported separately with their original textures and
color values. Layered colors, including Sword's iris layer, are baked. Before
sharing an animated rig, `appearance_glb.py` verifies matching mesh positions,
UVs and indices, then embeds and addresses the rare materials
using `extras.rae.shinyMaterialIndex`. It also supports per-form material maps.
`sv_cosmetics.py` reads TRMMT's embedded color selectors; Squawkabilly's four
palettes each have their own normal and rare material sets. `swsh_forms.py`
exposes Alcremie's seven source sweet groups for each flavor.
Sword's transparent sprite layers preserve their original alpha, UV-set choice
and multiplicative color layers. `repair_swsh_appearance` can rebake these static
materials on an existing animated export; `compact_glb` removes superseded images
without rewriting the animation buffers.
Color and layer texture coordinates apply the source transform
`base + scale * (uv + translate)` and each sampler's repeat, clamp or mirrored
repeat mode before baking. The version 3 repair covers the entire Sword batch,
including opaque body materials such as Galarian Ponyta. Equivalent per-mesh
material copies may share a geometry match only when their semantic role,
embedded texture bytes, sampler and rendering values all agree.
Finalization also recognizes inactive zero-light emission envelopes from their
source premultiply/blend/depth state and entirely black color map. These retain
their geometry and use neutral additive black instead of an alpha-black surface
that obscures the real body (Galarian Rapidash's horn glow is one example).

Sword meshes and evaluated bone translations/binds are converted together from
centimeters to meters. Its scale-compensated source bones are sampled under one
identity skeleton root to avoid inheriting the same scale twice. All original
skeletal clip names and durations remain; material-only GFBA clips and shader
effects stay raw. Shader-only effect-mask passes without a portable base color
are omitted from the derived geometry rather than rendered as opaque cards.

An absent source rare material is recorded as `shinyAvailable: false`; the batch
exports that visual mode in normal colors and reports the missing rare palette.
It never substitutes a generated recolor. Scarlet's story ride models are
examples; their ordinary battle forms have original normal and rare materials.
Ogerpon's `_99` crystal-mask files are attachments, retained as source components
and excluded from the standalone Pokémon inventory.

`finalize_batch` rechecks raw hashes, clip identity and Khronos validation after
appearance passes, refreshing export/progress reports. The consuming app must
also validate the final GLB hash with its own loader before installation.

## Scan results (Pokémon Scarlet)

Typical first scan after hash cache download:

- ~993 Pokémon ``.trmdl`` models
- ~17k ``.bntx`` textures (Pokémon + maps + characters + icons)
- ~51k ``.tranm`` / ``.gfbanm`` animations (Pokémon)
- 24 loose RomFS files (audio, Trinity headers, movies)

## Development notes

- No imports from other ``platforms/*``.
- UI uses ``PlatformDispatch`` only.
- Tests: ``pytest tests/test_switch_platform.py tests/test_platform_import_isolation.py``.
