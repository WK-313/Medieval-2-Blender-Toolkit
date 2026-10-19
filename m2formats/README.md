# Medieval II format engine

Vendored on 2026-10-08 from the shared Unit Transfer repository,
`main/unittransfer/`, at source checkout commit
`bf4a8fcdaa7b41dc6ac4772a0ab8bbd6b4dac101`.
The file hashes below identify the exact working-copy inputs (before newline
normalization), independently of checkout changes. The refreshed CAS hash records
its LF-normalized source snapshot; the other entries retain the original inputs.

This package imports without Blender, Pillow, web catalogues, or Unit Transfer
installed. Import its modules directly; it does not register Blender classes.

CAS reader/writer refreshed on 2026-10-14 from source commit
`416062896cfdc37a70fb0152284f60dafb6d6c6d`. `write_cas(scene)` returns bytes
without writing to the source file. Complete scenes preserve opaque records while
serializing editable fields; partially decoded scenes can only round-trip unchanged.
Baked animation keys are retained, with hierarchy/key-time edits refused.
The application-specific `texture_rel` pack lookup is omitted from this snapshot.
External texture entries have no material-name field: keep `CasMaterial.name` empty.
Fresh files use exporter chunk order, computed skeleton size, and mesh closing counts.

## Local adaptations

- All Python files use LF line endings.
- `cas.py`: `from unittransfer import mesh` becomes `from . import mesh`; omit
  `texture_rel`, whose mod/game pack lookup belongs to the donor application.
- `mesh.py` and `casanim.py`: no changes other than line endings.
- `modelexport.py`: omit `texture_to_dds`, `dds_to_texture`, `glue`, and
  `entry_export`; remove the `sprites` import. The retained
  skeleton, GLB, OBJ, and `texture_case` routines are unchanged. Texture
  preparation and mod-entry selection belong to the addon integration layer.
- `animpack.py`: retain the original reader/codec/cache section through
  `packs_for`, plus `resolve_slot`. Omit the subsequent pack-port planning,
  pack mutation, backup/logging, and compaction workflows. Remove their unused
  hashlib/shutil/subprocess imports. Retained codecs still serialize their
  in-memory records; the package does not expose the omitted mod-write workflows.
- `i18n.py`: small English-only `msg` adapter retaining source formatting
  behavior, including format specifications and unresolved placeholders.
- Original source docstrings are preserved as provenance, including descriptions
  of application features omitted here. They describe the upstream module;
  the supported vendored scope is the retained API documented above.

To update, compare the corresponding source files, reapply only these adaptations,
and run the format and Blender bridge tests before replacing this copy.
Original comments and notices are retained. No standalone license file or license
header was present in the source files or repository root at vendoring time;
this provenance record does not add or assert a license grant.

## Input SHA-256

| Source file | SHA-256 |
| --- | --- |
| `mesh.py` | `d1c7622759f7c400281dad7d60b11c0230ebf00c7810ff6bf47edf0f36ff1329` |
| `cas.py` | `270a8df50705a5731b1f55266fd4b29205b665dc846dffff72ff5977428af9b6` |
| `casanim.py` | `e89777f9b4e68243400085d684a0c451275c84c1ad60ea9a0360745544405ecf` |
| `animpack.py` | `97d9ab82bd663493088c65381d765d3eebe6bb0e972bb3364cff63b7f81b1d41` |
| `modelexport.py` | `7c5da3ef6215582947327932eb8eff4a7df1f520f8b65537ebd7dcdca01e5d1d` |

## Animation slot labels (2026-10-16)

`skelslots.py` retains the donor slot-name lookup and family grouping only;
comparison/reporting and application integration are omitted. `data/skeleton_slots.json`
is copied unchanged. Source checkout: `3cfef41839a34bf0ad59f8912fc3c04622cb8876`.

- `skelslots.py`: SHA-256 `d6d7cf08b8edd26bf0bd039d0cb0c995005fe4a46efa3186d45350ec05bb002e` (original input).
- `data/skeleton_slots.json`: SHA-256 `b38b435c5df4a2b98c7c60b893dd77e558a4b46b66c998d38d55f132c43d816a` (original input).

## Model database reader (2026-10-18)

`modeldb.py` retains the donor parser, entry records and raw-text serialization through
`parse_entry`; repair and editing workflows are omitted. The two BOM constants are
inlined from keyblock to avoid application dependencies. Original source SHA-256: `5846a00a99bed32a9a2e0064c0ae0857325a4d0a96e46817e4f76bdd94c92cdd`.
Source checkout: `3cfef41839a34bf0ad59f8912fc3c04622cb8876`.

## Engine readers (2026-10-19)

`engines.py` retains engine/model-group and engine-skeleton records, parsing and raw
serialization, plus embedded texture-path lookup. Editing helpers are omitted.
Raw text is decoded directly as Latin-1 without the keyblock dependency.
Original source SHA-256: `636498fc0d6797c8bdcaafb6fcef27c92bb5314d2d51c5e26e898a5210bca5ad`.
