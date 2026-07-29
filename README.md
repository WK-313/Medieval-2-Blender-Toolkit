# Medieval 2: Total War - Blender Toolkit

This Blender addon is a complete asset pipeline for Medieval II: Total War modding. It imports the game's units, models and settlements straight into Blender, and exports finished models back into the game's formats — including textures, normal maps and a ready-made `battle_models.modeldb` entry — with IWTE handling the final `.mesh` conversion.

The addon is organised into four **workmodes**, selected from a dropdown at the top of the toolkit panel (N-panel → Medieval 2 Toolkit). Each workmode shows only the panels relevant to that stage of the pipeline.

> **Blender 5.0 or newer is recommended** — that is what the addon is developed and tested against.

***

[![Build Status](https://img.shields.io/github/v/release/WK-313/Medieval-2-Toolkit?style=for-the-badge)](https://github.com/WK-313/Medieval-2-Toolkit/releases) [![Build Status](https://img.shields.io/github/downloads/WK-313/Medieval-2-Toolkit/total?style=for-the-badge)](https://github.com/WK-313/Medieval-2-Toolkit/releases)

## Table of Contents
* [Features](#features)
* [Usage](#usage)
* [Installation](#installation)
* [Credits](#credits)

## Features

### Unit Import
Read any mod's data folder and pull its content into Blender:
- Batch import every unit of a faction, or import single units and officers
- Import Faction brings in **every armour upgrade** of each unit, stacked upward on Z, plus an optional **Import Officers** toggle that places each unit's officers behind it
- Single unit import has tick boxes for the armour upgrade levels the unit actually has, each labelled with its model ID
- Import models directly from the battle_models.modeldb (BMDB) with faction filtering, and texture variants labelled "(Same as X)" so the genuinely unique ones stand out
- EDU-based unit browser with mount / officer / upgrade handling
- Imported Models list with a "Delete objects with the entry" toggle, so removing an entry also deletes the rig and everything parented to it
- Unit card renderer setup and unit variation randomizer
- Batch import strategy `.cas` models

![Unit Import — Paths and EDU](./images/Unit_Import1_Menu_Paths%2BEDU1.png)

![Unit Import — import buttons and Imported Models list](./images/Unit_Import2_Menu_EDU2.png)

![Unit Import — BMDB browser](./images/Unit_Import3_Menu_BMDB.png)

### Unit Export
Take a rigged model from Blender back into the game:
- One-click **Check Model for Export**: auto-fixes naming (`.001` suffixes, `x__y` part naming), collapses duplicate materials and material slots, validates weights, texture sizes and UV layout before anything leaves Blender
- One consistent export naming rule: `name` → `name__name`, `name1_name2` → `name1__name2`, and number-suffixed parts (`hair1`, `hair_1`) → `name__name_number`, with unresolvable `.001` clashes renumbered to `base_01`, `base_02`, ...
- Main/attach material auto-detection (`_at`/`attach`/`attachment` names, lone-material fallback) with any extra materials folded in automatically
- Per-texture UV checking: main-texture objects must sit in the first UV tile, attach-texture objects in the tile to the right, with an option to auto-select offending objects in the UV editor — plus an **Attempt to Auto-Assign UV** button
- GLB export with automatic texture conversion to the game's `.texture` format (DXT5, via bundled texconv), including non-DXT `.dds` sources (uncompressed, BC7, DX10 header) which are recompressed rather than skipped
- Any texture that cannot be converted is reported with a reason in the completion popup instead of failing silently
- Output renaming for all textures, and blank normal-map generation for materials without one
- BMDB entry generator: faction ownership toggles, sprite/footer copying from existing units, duplicate-entry warning against the mod's modeldb
- GLB → `.mesh` conversion driven through IWTE task files, with progress monitoring
- All export settings are stored per-armature, so multiple units can live in one .blend

![Unit Export — paths and model check](./images/Unit_Export1_Path%2BArmature.png)

![Unit Export — materials, textures and BMDB entry](./images/Unit_Export2_Material%2BBmdb.png)

![Unit Export — sprite copy, export and IWTE conversion](./images/Unit_Export3_Copy%2BExport%2BIWTE.png)

### Settlements
- Import settlement `.world` models through IWTE
- Browse and sort the mod's settlement packs

### QOL (rigging & cleanup tools)
- Weight transfer between meshes with selectable vertex mapping, followed by an automatic vertex group smoothing pass on each target mesh
- Parent meshes to bundled game skeletons: plain parenting, rigging with sample body weights, or a full setup that also brings in equipment props
- Rename tools: clean `.001` number suffixes, switch bone case (`_R/_L` ↔ `_r/_l`), apply/swap game part prefixes (`weapon0__`, `shield0__`, ...), toggle the `__opt` optional-part suffix
- SimpleBake helpers for texture baking workflows

![QOL workmode](./images/QOL.png)

## Usage

For written instructions, please refer to this [Google Doc](https://docs.google.com/document/d/1sjLq0buiZpiRU4AwekeG9lYVo7wYgm7mhbN25glYwIc).

For a video walkthrough of the tool, watch the tutorial on YouTube:

[![Medieval 2 Toolkit tutorial](https://img.youtube.com/vi/rgbFm3ErtHk/maxresdefault.jpg)](https://www.youtube.com/watch?v=rgbFm3ErtHk)

## Installation

## 1. Download the release
Navigate to the [latest release](https://github.com/WK-313/Medieval-2-Toolkit/releases/latest) and download the zip file under the **Assets** section

## 2. Install the addon

**The quick way — drag and drop.** With Blender already open, drag the downloaded `.zip` straight onto the Blender window and confirm the install dialog. That is all there is to it.

> If you are **updating** an existing install, restart Blender afterwards for the changes to take effect.

**Otherwise, install it manually.** Open `Edit → Preferences`:

![Edit menu → Preferences](./images/Install%201.png)

Go to the **Add-ons** tab, open the dropdown in the top right and pick **Install from Disk...**, then point it at the downloaded `.zip` file:

![Add-ons → Install from Disk](./images/Install%202.png)

## 3. Enable the addon
Search for `medieval` in the add-on list and tick `Medieval 2 Toolkit` if it is not enabled already:

![Enable Medieval 2 Toolkit](./images/Install%203.png)

## 4. Install IWTE
The toolkit uses **IWTE** for the final `.mesh` and `.world` conversions. Download the **latest version** of IWTE from [makanyane/IWTE](https://github.com/makanyane/IWTE) and point the toolkit's `IWTE` path at its folder in the Paths panel.

## Credits
- `WK | Kautto Ville`
    - Discord: `wk__`
- `ProJYeet` — Unit Export and QOL workmodes, BMDB writer, importer fixes
    - Discord: `projyeet`
- `Medik`
- `Wilddog` and `Makanyane` — for IWTE
