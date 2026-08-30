# Medieval 2: Total War - Blender Toolkit

This Blender addon is a complete asset pipeline for Medieval II: Total War modding. It imports the game's units, models and settlements straight into Blender, and exports finished models back into the game's formats — including textures, normal maps and a ready-made `battle_models.modeldb` entry — with IWTE handling the final `.mesh` conversion.

The addon is organised into six **workmodes**, selected from the strip of buttons at the top left of the toolkit panel (N-panel → Medieval 2 Toolkit). Each workmode shows only the panels relevant to that stage of the pipeline. If you preferred the older look, **QOL → Interface → Panel layout** switches back to the classic grid of workmode buttons with ordinary Blender sub-panels underneath; the choice is kept in your Blender preferences, so it holds for every file.

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
- **Import Faction and Import Full Unit run with a progress bar** instead of freezing Blender. The bar names the model being imported and counts through the queue (England is 91 units and 276 models), the view keeps updating as they land, and **Esc** stops the batch and reports what was brought in. A model that fails is listed at the end rather than taking the rest of the import down with it
- Anything not yet converted is extracted **once for the whole batch** before the import starts, rather than re-running IWTE for each unit in turn, and that conversion is watched with its own counter
- Single unit import has tick boxes for the armour upgrade levels the unit actually has, each labelled with its model ID
- Import models directly from the battle_models.modeldb (BMDB) with faction filtering, and texture variants labelled "(Same as X)" so the genuinely unique ones stand out
- EDU-based unit browser with mount / officer / upgrade handling
- **M2TWEOP units** are read alongside `export_descr_unit.txt`: a mod's own `eopData/unitTypes` folder is found on its own, and the Paths panel's `EOP Units` field points at them if the mod keeps them somewhere else. An EOP unit imports, exports and cards exactly like an EDU one
- Imported Models list with a "Delete objects with the entry" toggle, so removing an entry also deletes the rig and everything parented to it
- Unit variation randomizer
- Batch import strategy `.cas` models

![Unit Import — Paths and EDU](./images/Unit_Import1_Menu_Paths%2BEDU1.png)

![Unit Import — import buttons and Imported Models list](./images/Unit_Import2_Menu_EDU2.png)

![Unit Import — BMDB browser](./images/Unit_Import3_Menu_BMDB.png)

### Unit Export
Take a rigged model from Blender back into the game:
- One-click **Check Model for Export**: auto-fixes naming (`.001` suffixes, `x__y` part naming), collapses duplicate materials and material slots, validates weights, texture sizes and UV layout before anything leaves Blender
- One consistent export naming rule: `name` → `name__name`, `name1_name2` → `name1__name2`, and number-suffixed parts (`hair1`, `hair_1`) → `name__name_number`, with unresolvable `.001` clashes renumbered to `base_01`, `base_02`, ...
- Main/attach material auto-detection: `_main` picks the main texture, `_at`/`attach`/`attachment` the attachment one, with a lone-material fallback and any extra materials folded in automatically. Neither slot is filled by guesswork — a rig whose materials cannot be told apart by name says so instead of adopting whichever material came first
- Per-texture UV checking: main-texture objects must sit in the first UV tile, attach-texture objects in the tile to the right, with an option to auto-select offending objects in the UV editor — plus an **Attempt to Auto-Assign UV** button
- GLB export with automatic texture conversion to the game's `.texture` format (DXT5, via bundled texconv), including non-DXT `.dds` sources (uncompressed, BC7, DX10 header) which are recompressed rather than skipped
- Any texture that cannot be converted is reported with a reason in the completion popup instead of failing silently
- Output renaming for all textures, and blank normal-map generation for materials without one
- BMDB entry generator: faction ownership toggles, sprite/footer copying from existing units, duplicate-entry warning against the mod's modeldb
- The entry can go to any of three places, switched per rig with **Text File** / **Install to Mod** / **Both**:
  - **Text File** (the default, and what earlier versions did): the export writes `<mesh name>_bmdb.txt` beside it, to paste into `battle_models.modeldb` by hand. Nothing in the mod is touched
  - **Install to Mod**: the toolkit writes it into the mod itself, described below
  - **Both**: the text file *and* the install, from the same entry text — so the `.txt` is a record of exactly what went into the mod
- **Probe BMDB** answers "what would this entry do to the mod?" without writing anything, in every mode: whether the name already exists, what Rename / Overwrite / Skip would do about it, and every file the install would touch. Worth a press before pasting an entry in by hand as much as before installing it
- **Load Entry From Mod** pulls an existing `battle_models.modeldb` entry — mesh path, texture names, sprite, animation footer and faction ownership — straight into those fields, so an entry can be edited in Blender and written back. It is no longer a button in the panel; run it from the F3 search menu ("Load Entry From Mod")
- **Install to Mod** writes the entry into `battle_models.modeldb` and copies the `.mesh` and `.texture` files into the mod for you, with the entry count in the file header kept correct. Its controls sit at the bottom of the same BMDB Entry panel, appearing as soon as the mode is switched. Nothing is written before you have seen the full plan:
  - an entry of the same name that is byte-identical is left alone; one that differs can be **renamed** (first free `name_2`, `name_3`, ...), **overwritten** or **skipped**
  - an overwrite says what it costs first: extra LODs dropped, faction skins lost, skeleton changes, and which EDU units use the entry
  - every file is byte-compared against the mod's copy — identical ones are not recopied, differing ones are either kept or overwritten, and a differing file shared with other models names those models before it re-skins them
  - `battle_models.modeldb` is backed up to a timestamped `.bak` **twice** before the entry is written — once next to itself in the mod, and once into the export folder beside the mesh and textures the install came from, so the copy travels with the exported unit and is not buried among the mod's own files. Either one puts the modeldb back byte for byte. It is rewritten through a temp file, so a failure cannot leave a half-written modeldb
- GLB → `.mesh` conversion driven through IWTE task files, with progress monitoring
- **A conversion that runs long asks what to do with it** rather than waiting silently forever: keep waiting (the default - a big model genuinely takes minutes), open the system console to watch the toolkit's output, or abort. It asks after three minutes and backs off each time, so a long job is not a nag. IWTE is never stopped on a timer alone
- **Sample task files** ship with the addon, one per QOL skeleton (2H, Archer, Crossbow, Jav, Spear, Sword). They carry that skeleton's bone order and case, which is what IWTE writes into the `.mesh`, so the right one matters. A rig parented through **Parent to Skeleton** is given its skeleton's file automatically; the Sample Task Files section at the bottom of the Export panel switches between them, and browsing to a task file of your own still overrides everything
- All export settings are stored per-armature, so multiple units can live in one .blend

![Unit Export — paths and model check](./images/Unit_Export1_Path%2BArmature.png)

![Unit Export — materials, textures and BMDB entry](./images/Unit_Export2_Material%2BBmdb.png)

![Unit Export — sprite copy, export and IWTE conversion](./images/Unit_Export3_Copy%2BExport%2BIWTE.png)

### Unit Info (unit cards)
Render a whole faction's unit cards and unit info images without leaving Blender:
- **Import Units for Cards** brings in one armour upgrade of every unit of a faction, evenly spaced on X so each one can be framed on its own. Models and textures that are not on disk yet are extracted with IWTE first, exactly like the Unit Import workmode — nothing has to be converted by hand
- Variations are rolled down to one mesh per group on import, so a card never shows a pile of overlapping heads and weapons
- The Imported Models list gets a **tick box per unit**, plus a search box, A→Z / Z→A sorting and a foot / mounted / engine / added-by-hand filter, drawn above the list in both the Unit Import and Unit Info tabs
- Entries **remove themselves** when the armature they point at is deleted from the file (*Drop entries for deleted objects*, on by default). An object merely unlinked from the scene is left alone. Removing an entry with *Delete objects* on also takes the unit's control rig with it, rather than stranding it
- Entries **follow the armature when you rename it** — the list updates itself, keeps pointing at the right rig, and a rename no longer costs you the entry. *Remove item* and *Purge list* are on the Card Units list as well, so a unit can be dropped without switching workmode
- **Add Selected / Add All Unlisted** puts armatures that never came through the importer — hand-built units, a `.glb` dragged straight in — into the Imported Models list, so they can be given a card too. Selecting a control rig adds the skeleton it drives, not the controller
- A **mount or siege engine is one entry** with a **disclosure arrow**. Those units import as several armatures — the horse or the engine plus one per rider or crew member — and the entry folds them underneath it, showing the total beside the name; the arrow opens them as indented sub-rows with a tick box each. Sorting keeps a unit's parts directly under it, and a search that happens to match a rider never leaves a row hanging under nothing. Removing the unit entry takes its parts with it; removing a sub-entry takes only that one armature. A mount imported before this existed, or built by hand, is grouped the moment **Add Selected** picks it up
- **Create Card Cameras** gives every ticked unit — or, with nothing ticked, every selected armature — its own orthographic card camera, each carrying a sun aimed the same way at strength 4. Only the sun of the unit being rendered is lit, so fifty cameras do not stack fifty suns onto every card. A mount gets **one camera for the whole unit**, not one per rider: ticking a rider means "card this unit", not "give the rider a camera". Tick **Control Rig** in the same box and it also builds each unit's IK controller in one go, so the units can be posed before rendering; units that already have one are left as they are
- On a mount or an engine that means **a controller per rider and crew member, all in the same press**. The mount or the engine itself is skipped — no bone of a horse or a catapult is on a human IK controller, so it would drive nothing — and each rider's controller is kept parented under the mount, so giving a rider IK handles does not lift it off its horse
- Cameras, suns and control rigs are all created **in the unit's own collection**, not loose in the scene, so a faction import stays organised
- A unit standing **half in the ground** is set down on it first — raised by exactly how far its lowest point is below `z=0`, so the fixed card camera frames it like every other unit. A unit already above the floor, or one deliberately parked below the scene, is left alone (*Set units standing in the ground onto it*, on by default)
- Card presets for the 48x66 unit card, the 68x90 variant and the 180x230 info card, plus a custom size. **Supersampling** renders a whole multiple of the card and the compositor scales it back down — at the default of 10 a unit card renders at 480x660, the size the old card .blend files used
- The card compositor reproduces the old card .blend node tree, frame for frame: a *rescale* frame (bilateral blur at size 5 / threshold 1, then a Nearest Transform back to card size), a *Colour Adjust* frame (brightness/contrast bracketed by a pair of **Alpha Convert** nodes so it works on straight alpha, then gamma, exposure and RGB curves) and a *Sharpen* frame (Diamond Sharpen at 0.2, then hue/saturation). Because the rescale comes first, the sharpen bites at final card pixel size, which is what gives those cards their crispness. The old *Border Size* frame is not reproduced: it held nothing visual and only existed to crop the output canvas, which no Blender 5 node can do any more — the card is cut out of the middle of the frame when it is saved instead
- **Line Art Outline** (on by default) adds one Grease Pencil **Collection Line Art** object per unit collection, each outlining only its own unit. The outlines follow the scene camera rather than being pinned to one card camera, so a single outline object covers every unit in its collection. Contour with no silhouette filtering, plus material borders, edge marks and loose edges, in black, with 2D stroke depth order and a stroke depth offset so it never drops out in patches against the surface it traced. Thickness is set in *finished-card pixels*, so 0.5 is a half pixel outline on the card no matter the supersampling or card size
- **Keep full-size render** saves the card render before the compositor scales it down, as an uncompressed PNG in a `full` subfolder beside each card. It costs an extra render pass per unit, with the rescale switched off
- **Keep HD render** renders each unit a second time at a whole multiple of 48x66 — 10x, 20x, 30x or 40x, so up to 1920x2640 — into an `hd` subfolder. A picture of the unit rather than a card: the rescale and the smoothing blur are both switched off for the pass, and the camera widens so nothing the card frames falls outside it
- The compositor group is left fully tweakable — anything changed in it survives, and it is only rebuilt when the toolkit's own node chain changes version or **Rebuild compositor** is ticked
- **Render Cards** renders one image per card camera straight into `units\<dir>\#<unit>.tga` / `unit_info\<dir>\<unit>_info.tga`, honouring each unit's `card_pic_dir` / `info_pic_dir` and falling back to the owning faction's folder. Point the Card Output path at the mod's `data\ui` folder and the files land where the game expects them
- **Isolate unit while rendering** (on by default) switches everything except the unit being carded off for the length of that render, so a neighbour reaching into the frame cannot land on the card, and puts it all back before the next camera. *Visible only* narrows that to the visible part of the unit and leaves anything hidden by hand — a spare helmet, a second shield — off the card. On a mount or an engine a third control appears: **Whole unit** keeps the mount and everyone riding it, **Ticked parts** keeps only the armatures ticked under that unit in the list — so untick the rider to card the horse on its own, or untick the mount to card the rider on its own, without deleting anything. Unticking every part falls back to the whole unit rather than writing an empty card
- **Open renders when finished** (on by default) loads every card the run wrote — including the full-size and HD passes — and shows them in a second window's Image Editor, zoomed to fill it rather than sitting there at 48 pixels across, so a batch can be checked without hunting through folders. Its image dropdown steps through the rest, and the next render refills that same window instead of stacking up another one

![Unit Info — paths, Card Units list and the pose library](./images/Unit_Card1.png)

![Unit Info — card size, supersampling, HD pass and line art](./images/Unit_Card2.png)

![Unit Info — cameras, lighting, rigs and the render panel](./images/Unit_Card3.png)

### Strat (campaign map models)
Turn a finished battle unit into a campaign map model, in one or two clicks instead of the nine-step manual process.

The strat skeleton is the battle skeleton with the clavicals, jaw, eyebrow and weapon groups taken away and three cloak bones plus a particle node added, and a strat model carries **one mesh, one texture and one bone per vertex**. Getting there by hand means combining the two textures in another addon, stripping bones and re-rigging whatever was weighted to them, joining everything, limiting weights, and scaling both UV islands into the combined texture. **Create Strat Model** does all of it:

- **Combines the main and attachment textures** into a single `.tga` and remaps the UVs to match. No Material Combiner needed — the atlas is built to a known layout, so the UV transform is exact rather than a guess. *Square* puts the two textures along the top of a square texture (the layout the community guide uses); *Half Height* wastes nothing at the same resolution per texture
- **Folds orphaned weights into their nearest surviving bone** — a clavicle's weights onto the torso, a jaw's onto the head, a bowstring's or weapon group's onto the hand — instead of dropping them. Dropped weights are what causes IWTE's *"Some vertices have no bone weights and have been assigned to the models first bone eg pelvis"* warning and limbs trailing off the model in game
- **Welds anything still loose** to its nearest weighted neighbour, so the model converts without that warning at all
- Matches the rig's own bone name case, uppercase or lowercase, automatically
- Joins every mesh, re-rigs onto the strat skeleton, and gives each vertex exactly one bone at weight 1.0
- Builds on a **copy in its own collection** by default, so the battle unit you imported is still there afterwards

Then **Convert to .cas (IWTE)** writes the `extract_to_cas` task file and runs the conversion with a progress bar — the same job as IWTE's *Model Files → Cas Models → dae/ms3d to cas_mesh*, without leaving Blender. **Build + Convert** does the whole thing in one press.

Afterwards, **Check .cas Texture** reads the texture name back out of the converted `.cas` and compares it with the texture that was written — a mismatch there is what crashes the campaign map on load, and it is otherwise found by opening the binary in a text editor. **Copy to Mod** puts the `.cas` and its `.tga` into the mod. The `descr_character.txt` entry is still yours to write.

> Start from a unit imported through **Unit Import**, with its main and attachment materials set (running **Check Model for Export** in the Export workmode is the easy way — the Strat workmode reads the same two materials).

### Settlements
- Import settlement `.world` models through IWTE
- Browse and sort the mod's settlement packs

### Poses (in the QOL workmode)
A pose asset library ships with the addon and registers itself the first time the addon is enabled — no setup:
- Little **pose buttons in the bottom-left of the viewport** whenever an armature is selected: enter/leave pose mode, open/close the pose library, and (in pose mode) save a new pose
- Entering pose mode splits an **asset browser** off the viewport, already pointed at the library and filtered to `Poses/IK Full`
- With an armature selected, **double-clicking a pose applies it** — from object mode as well, so quick poses need no mode switching. The toolkit handles the double-click itself (Blender's own handler is muted while the addon is on; untick *Double-click applies poses* to hand it back), which is what lets it work outside pose mode, land the pose on the right rig, and warn first
- Most of the library poses the **IK control rig**, not a Medieval 2 skeleton — of the 231 bundled poses, roughly 180 animate `IK Pelvis` / `IK frist left` / `Pole` / `Switch`, bone names a game skeleton simply does not have. Double-clicking one with only the unit selected walks up to its controller automatically — through the parenting, or through the constraints the controller left on the unit's bones, so a controller that was appended, re-parented or built by an older addon is found just the same. If the unit has none, the panel says so and offers **Add Control Rig**. The rig the pose lands on is then **selected and made active** — so the controller is already in hand to adjust, and pose mode follows it (*Select the rig the pose lands on*, on by default)
- If the rig is already animated, applying a pose asks first: it lists the actions and their keyframe count, and applying **deletes every one of those keyframes** before setting the pose
- **Create Pose Asset** saves the selected bones' pose straight into the library, with a dialog for the name, the catalog to file it under, and an optional new sub-catalog
- **Textures to Assets** builds one asset-marked material per texture in a folder, pairing each with its `_normal`/`_norm`/`_nrm`/`_bump` map

> Poses you create land in the addon's own `assets\Saved` folder. Copy that folder somewhere safe before updating the toolkit — reinstalling replaces the addon directory.

### QOL (rigging & cleanup tools)
- Weight transfer between meshes with selectable vertex mapping, followed by an automatic vertex group smoothing pass on each target mesh
- Parent meshes to bundled game skeletons: plain parenting, rigging with sample body weights, or a full setup that also brings in equipment props. Whichever skeleton is used is remembered on the rig, and the Unit Export panel picks up that skeleton's IWTE sample task file by itself
- **IK control rig**: build the `IK_Infantry`, `IK_Archer` or `IK_Dwarf` controller for a selected skeleton, the same three rigs the v0.9.x toolkit generated. The controller is parented over the unit and every non-weapon bone is constrained to it, so the unit follows the IK handles — and the bundled pose library, which is written against these bones, works. **Remove Control Rig** un-parents and un-constrains cleanly. **Whole unit** (on by default) covers a mount or a siege engine in one press: a controller for every rider and crew member, the mount or engine itself skipped, and each controller parented under the mount so the riders stay on it
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

**On Linux and macOS:** IWTE and the bundled `texconv` are Windows programs, so the toolkit runs them through **Wine**, the same way Medieval 2 itself is run there. Install Wine and make sure `wine` is on your `PATH`; the rest of the addon is native. A native `texconv` on your `PATH` is used in preference to the bundled one.

## Credits
- `WK | Kautto Ville`
    - Discord: `wk__`
- `ProJYeet` — Unit Export and QOL workmodes, BMDB writer, importer fixes
    - Discord: `projyeet`
- `Medik`
- `Wilddog` and `Makanyane` — for IWTE
- The *Quick Tutorial For Strat Models w/ Blender and IWTE* guide and its `createStratModel.py`, which the Strat workmode is built from
