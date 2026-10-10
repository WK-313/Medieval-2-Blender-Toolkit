# Medieval 2: Total War — Blender Toolkit

A complete asset pipeline for Medieval II: Total War modding, inside Blender. Import a mod's units, models and settlements, work on them, and export them back into the game's formats — textures, normal maps and a ready-made `battle_models.modeldb` entry included — with IWTE handling the final `.mesh`, `.world` and `.cas` conversions.

[![Latest release](https://img.shields.io/github/v/release/WK-313/Medieval-2-Blender-Toolkit?style=for-the-badge)](https://github.com/WK-313/Medieval-2-Blender-Toolkit/releases) [![Downloads](https://img.shields.io/github/downloads/WK-313/Medieval-2-Blender-Toolkit/total?style=for-the-badge)](https://github.com/WK-313/Medieval-2-Blender-Toolkit/releases)

> **Blender 5.0 or newer is recommended** — that is what the addon is developed and tested against. Windows, Linux and macOS.

The addon lives in the 3D viewport sidebar (`N` → **Medieval 2 Toolkit**) and is split into six **workmodes**, selected from the button strip at the top left. Each shows only the panels for that stage of the pipeline. **QOL → Interface → Panel layout** switches back to the classic grid of workmode buttons if you prefer it.

## Table of Contents
* [Features](#features)
* [Usage](#usage)
* [Installation](#installation)
* [Credits](#credits)

## Features

### Unit Import

Read any mod's data folder and pull its content into Blender.

- Batch import a whole faction, single units, officers, or models straight from `battle_models.modeldb`
- **Import Faction** brings in every armour upgrade of each unit, stacked on Z, with an optional **Import Officers** pass
- Batch imports run with a **progress bar**, keep the viewport updating, cancel on `Esc`, and list failed models at the end instead of aborting. Anything unconverted is extracted once for the whole batch
- Single unit import has a tick box per armour upgrade level, each labelled with its model ID
- **M2TWEOP units** are read alongside `export_descr_unit.txt`; a mod's `eopData/unitTypes` folder is found automatically
- BMDB browser with faction filtering, search, and texture variants labelled `(Same as X)` so unique ones stand out
- Imported Models list with tick boxes, search, sorting, type filters, and optional deletion of the objects with the entry
- Unit variation randomizer, and batch import of strategy `.cas` models

![Unit Import — Paths and EDU](./images/Unit_Import1_Menu_Paths%2BEDU1.png)

![Unit Import — import buttons and Imported Models list](./images/Unit_Import2_Menu_EDU2.png)

![Unit Import — BMDB browser](./images/Unit_Import3_Menu_BMDB.png)

### Unit Export

Take a rigged model from Blender back into the game.

- **Check Model for Export** validates and auto-fixes a rig in one press: part naming (`x__y`), `.001` clashes, duplicate materials and slots, main/attach material detection, vertex weights, UV maps and tile placement, texture sizes and the IWTE task file. Every pass has its own tick box under **Check options**
- **Per-texture UV checking** — main textures in the first UV tile, attach textures in the tile to the right — with auto-select in the UV editor and an **Attempt to Auto-Assign UV** button
- **GLB export** with automatic conversion to the game's `.texture` format (DXT5, bundled texconv), mipmaps, and non-DXT `.dds` sources recompressed rather than skipped. Anything that cannot be converted is reported with a reason
- **Normal maps**: use the material's own, browse to a file on disk, generate a blank one, or **generate one from the diffuse** — a numpy port of the gimp-normalmap workflow, so no GIMP or external process is needed. The generated alpha is the game's specular map, so *Brightness* and *Contrast* set how shiny the unit reads
- **Ignore Diffuse Alpha** for units that come out see-through in game
- **BMDB entry generator** — faction ownership toggles, sprite and footer copied from any existing unit, and a duplicate-name warning against the mod's modeldb. The entry goes to a **Text File**, straight **into the mod**, or **Both**
- **Install to Mod** writes the entry into `battle_models.modeldb`, keeps the header count correct, and copies the `.mesh` and `.texture` files across. Nothing is written before you have seen the full plan: name clashes offer rename / overwrite / skip, an overwrite states its cost, files are byte-compared so identical ones are not recopied, and the modeldb is backed up twice — once in the mod, once beside the exported files
- **Probe BMDB** answers "what would this do to the mod?" without writing anything, in every mode. **Load Entry From Mod** (F3 search) reads an existing entry back into the panel for editing
- **GLB → `.mesh` conversion through IWTE**, with a progress bar, an out-of-date IWTE warning, and a prompt to keep waiting, open the console or abort when a conversion runs long
- **Sample IWTE task files** for each bundled skeleton (2H, Archer, Crossbow, Jav, Spear, Sword), picked automatically from the skeleton the rig was parented to. Browsing to your own always overrides
- All export settings are stored per-armature, so several units can share one `.blend`

![Unit Export — paths and model check](./images/Unit_Export1_Path%2BArmature.png)

![Unit Export — materials, textures and BMDB entry](./images/Unit_Export2_Material%2BBmdb.png)

![Unit Export — sprite copy, export and IWTE conversion](./images/Unit_Export3_Copy%2BExport%2BIWTE.png)

### Unit Cards

Render a faction's unit cards and unit info images without leaving Blender.

- **Import Units for Cards** brings in one armour upgrade of every unit of a faction, spaced along X, extracting anything missing with IWTE. Variations are rolled down to one mesh per group, so a card never shows a pile of overlapping heads
- **Create Card Cameras** gives each ticked unit its own camera, light and collection, and optionally its **IK control rig** in the same press. A mount or siege engine gets one camera for the whole unit and a controller per rider
- **Projection** — orthographic or perspective (50mm on a 36mm sensor). Switching keeps the framing; only the foreshortening changes
- **Render mode** — **Rendered** (EEVEE, real materials, ambient occlusion, shadows and a grey world fill) or **Solid** (Workbench, flat unlit texture colour, far faster and needing no lamp). **Colour** sets the view transform, defaulting to Filmic
- The light stands back from the unit and above the camera axis, matching the reference card files, and stays parented to the camera so every unit in a faction-sized scene is lit identically
- **Camera Follows Selection** makes the selected unit's camera the scene camera, from the armature, its control rig, any of its meshes, or any part of a mount
- Presets for the 48x64 unit card, the 68x90 variant and the 180x230 info card, plus custom sizes. **Supersampling** renders a whole multiple and scales it back down
- The **card compositor** reproduces the original card `.blend` node tree — rescale, colour adjust, sharpen — with the rescale first, so the sharpen bites at final card pixel size. It stays fully tweakable and is only rebuilt when the node chain changes version
- **Line Art Outline** — one Grease Pencil Collection Line Art object per unit collection, with thickness set in finished-card pixels
- **Keep full-size render** and **Keep HD render** write extra passes into `full` and `hd` subfolders, the HD pass at up to 40x
- **Isolate unit while rendering** switches everything else off for the length of a render. *Visible only* leaves anything you hid by hand off the card; on a mount, **Isolate scope** cards the whole unit or just the ticked parts
- Units standing half in the ground are set down on it before their camera is built
- **Render Cards** writes straight to `units\<dir>\#<unit>.tga` and `unit_info\<dir>\<unit>_info.tga`, honouring each unit's `card_pic_dir` / `info_pic_dir`. **Open renders when finished** shows the whole batch in a second window's Image Editor

![Unit Cards — paths, Card Units list and the pose library](./images/Unit_Card1.png)

![Unit Cards — card size, supersampling, HD pass and line art](./images/Unit_Card2.png)

![Unit Cards — cameras, lighting, rigs and the render panel](./images/Unit_Card3.png)

### Strat (campaign map models)

Turn a finished battle unit into a campaign map model. The nine-step manual process — combining the two textures in another addon, stripping bones, re-rigging, joining, limiting weights and scaling both UV islands — is one button.

- **Strat Models browser** reads the selected mod's `descr_model_strat.txt`, with search by type or skeleton, faction textures, model LODs and shadow models. Select **Load Strat Models**, choose a variant, then **Import Strat Model**.
- **Built-in strat import** reads supported `.cas` files directly into editable meshes and a rig. Paths offers an IWTE import option, and older 2.x CAS files fall back to IWTE automatically. Missing files are reported; textures are resolved from the mod first, then vanilla data.
- Imported rigs retain their descriptor entry, faction, LOD and campaign scale in the `.blend`. Campaign scale stays as metadata so exporting does not bake it into the model. Importing does not change mod files.
- **Create Strat Model** combines the main and attachment textures into a single `.tga` and remaps the UVs exactly (no Material Combiner needed), folds weights from bones the strat skeleton lacks into their nearest surviving bone, welds anything still loose, joins every mesh, re-rigs onto the strat skeleton at one bone per vertex, and builds on a copy in its own collection
- Imported models can use the existing GLB/Convert workflow. Export preserves their bone order and stages the current diffuse image without changing scene materials; unchanged compatible DDS files are copied without recompression.
- **Convert to .cas (IWTE)** runs the conversion with a progress bar; **Build + Convert** does both
- **Triangle count** is shown before you build and in the report — the campaign map crashes on load above 10,000 triangles
- **Check .cas Texture** reads the texture name back out of the converted `.cas`; a mismatch there is what crashes the campaign map, and is otherwise found by opening the binary in a text editor
- **Open Output Folder** shows the converted `.cas` and its `textures\` folder. Copying them into the mod's `data/models_strat` and writing the `descr_model_strat.txt` entry are still yours to do

> Start from a unit imported through **Unit Import** with its main and attachment materials set — running **Check Model for Export** is the easy way, since the Strat workmode reads the same two materials.

### Settlements

- Import settlement `.world` models through IWTE, with a searchable, filtered list of the mod's settlement packs
- **Buildings** tools: **Align Building** and **Align All Buildings** rotate a building back onto the axis from its most common horizontal face normal, and **Find Building Copies** / **Find Unique Buildings** match on vertex count, face area and height, so a rotated or moved copy is still found

### QOL (rigging & cleanup)

- **Weight transfer** between meshes with selectable vertex mapping and an optional smoothing pass
- **Skeletons** — parent to a bundled game skeleton, rig with sample body weights, or a full setup including equipment props. The skeleton used is remembered and picks the matching IWTE task file
- **IK control rigs** — `IK_Infantry`, `IK_Archer` and `IK_Dwarf`, parented over the unit with every non-weapon bone constrained to them, which is what the bundled pose library is written against. **Whole unit** covers a mount or siege engine in one press. **Remove Control Rig** un-parents and un-constrains cleanly
- **Rename tools** — clean `.001` suffixes, switch bone case (`_R/_L` ↔ `_r/_l`), apply or swap game part prefixes (`weapon0__`, `shield0__`, …), toggle the `__opt` optional-part suffix
- **Clean UV Maps** on the selected meshes, and SimpleBake helpers

#### Pose library

A 231-pose asset library ships with the addon and registers itself on first enable.

- Pose buttons in the bottom-left of the viewport whenever an armature is selected; entering pose mode splits off an asset browser already pointed at the library
- **Double-click applies a pose**, from object mode as well. Most of the library poses the IK control rig, so the toolkit walks up to the unit's controller automatically — through parenting or through the constraints it left behind — and selects it ready to adjust
- Applying over an animated rig asks first and lists the keyframes it will delete
- **Create Pose Asset** saves the selected bones into the library; **Textures to Assets** builds one asset-marked material per texture, paired with its normal map

> Poses you create land in the addon's own `assets\Saved` folder. Copy it somewhere safe before updating — reinstalling replaces the addon directory.

![QOL workmode](./images/QOL.png)

## Usage

Written instructions: [Google Doc](https://docs.google.com/document/d/1sjLq0buiZpiRU4AwekeG9lYVo7wYgm7mhbN25glYwIc)

Video walkthrough:

[![Medieval 2 Toolkit tutorial](https://img.youtube.com/vi/rgbFm3ErtHk/maxresdefault.jpg)](https://www.youtube.com/watch?v=rgbFm3ErtHk)

## Installation

### 1. Download

Grab the `.zip` from the [latest release](https://github.com/WK-313/Medieval-2-Blender-Toolkit/releases/latest), under **Assets**.

### 2. Install

**Drag and drop** the `.zip` onto an open Blender window and confirm the dialog. That is all.

Or install it manually from `Edit → Preferences → Add-ons → ⌄ → Install from Disk…`, then search for `medieval` in the add-on list and tick **Medieval 2 Toolkit**.

| | | |
|---|---|---|
| ![Edit menu → Preferences](./images/Install%201.png) | ![Add-ons → Install from Disk](./images/Install%202.png) | ![Enable Medieval 2 Toolkit](./images/Install%203.png) |

> When **updating** an existing install, restart Blender afterwards.

### 3. Install IWTE

The toolkit uses **IWTE** for the final `.mesh`, `.world` and `.cas` conversions. Download the latest version from [makanyane/IWTE](https://github.com/makanyane/IWTE) and point the toolkit's `IWTE` path at its folder in the Paths panel.

**On Linux and macOS**, IWTE and the bundled `texconv` are Windows programs, so the toolkit runs them through **Wine** — the same way Medieval 2 itself is run there. Install Wine and make sure `wine` is on your `PATH`; a native `texconv` on `PATH` is used in preference to the bundled one. The rest of the addon is native.

## Credits

- **WK | Kautto Ville** — Discord `wk__`
- **ProJYeet** — Unit Export, Unit Cards, Strat and QOL workmodes, BMDB writer, importer fixes — Discord `projyeet`
- **Medik**
- **Wilddog** and **Makanyane** — for [IWTE](https://github.com/makanyane/IWTE)
- The *Quick Tutorial For Strat Models w/ Blender and IWTE* guide and its `createStratModel.py`, which the Strat workmode is built from
