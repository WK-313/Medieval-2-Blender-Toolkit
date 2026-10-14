# CAS writer validation

The writer belongs to Unit Transfer. The addon vendors its reader/writer snapshot with a relative mesh import; it writes bytes in memory and never writes to `scene.source`.

```powershell
python tests/v2c/test_writer.py
python tests/v2c/roundtrip_corpus.py --module-root Medieval-2-Toolkit-main --package m2formats --data-root "<mod>/data" --report tests/v2c/current-corpus.json
```

`test_writer.py` uses independently packed fixtures and checks byte preservation, known-field edits, geometry resizing, invalid scenes, opaque/baked records, version 3.02 editing and material ordering across chunks. Set `MED2_ADDON_SOURCE` to override addon discovery. Corpus checks are read-only and report every reader rejection.

For independent acceptance in IWTE, set `MED2_FORMAT_SOURCE` to the addon `m2formats` directory and `MED2_IWTE_EXE` to IWTE, then run Blender with:

```powershell
& D:/Blender-5.1.2/blender.exe --background --factory-startup --python-exit-code 1 --python tests/v2c/verify_iwte_writer.py
```

Fresh-file verification uses generated geometry, no game assets. Diagnostics are retained when extraction fails. This validates external format acceptance; loading a new campaign model in game belongs to the later export phase.

Historical corpus: 1,163/1,163 readable DaC/Reforged files were byte-identical (18 reader refusals out of 1,181). Those folders are absent from the current installed set. Current Heirs of Elendil corpus: 622/622 byte-identical, nine reader refusals out of 631. Partially decoded scenes can round-trip unchanged but cannot be edited; their opaque source records are retained explicitly.

Validated fresh files in IWTE, including zero-length/one-key and 201-key timelines, per-mesh geometry, bone pivots and full weights. Static meshes attach to the first nonroot bone in IWTE; the mixed fixture uses a zero-position pelvis and a nonzero child pivot. Material names must be empty for external textures. Failure scratch folders are kept for diagnosis.
