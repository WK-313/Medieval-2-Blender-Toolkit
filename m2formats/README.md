# Medieval II format engine

Vendored on 2026-10-08 from the shared Unit Transfer repository,
`main/unittransfer/`, at source checkout commit
`bf4a8fcdaa7b41dc6ac4772a0ab8bbd6b4dac101`.
The file hashes below identify the exact working-copy inputs (before newline
normalization), independently of checkout changes.

This package imports without Blender, Pillow, web catalogues, or Unit Transfer
installed. Import its modules directly; it does not register Blender classes.

## Local adaptations

- All Python files use LF line endings.
- `cas.py`: `from unittransfer import mesh` becomes `from . import mesh`.
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
| `cas.py` | `a8378b88bce9febe09f10ec6c2a4bedbb1001e2301d9fc407edd008954df0fb7` |
| `casanim.py` | `e89777f9b4e68243400085d684a0c451275c84c1ad60ea9a0360745544405ecf` |
| `animpack.py` | `97d9ab82bd663493088c65381d765d3eebe6bb0e972bb3364cff63b7f81b1d41` |
| `modelexport.py` | `7c5da3ef6215582947327932eb8eff4a7df1f520f8b65537ebd7dcdca01e5d1d` |
