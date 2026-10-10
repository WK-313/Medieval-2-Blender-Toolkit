"""Run with Blender --background --factory-startup --python-exit-code 1 --python FILE -- ..."""
import argparse
import importlib
import importlib.util
import json
import io
import zipfile
import ast
import math
import os
from pathlib import Path
import shutil
import struct
import sys
import tempfile
import types


def package(name, path):
    module = types.ModuleType(name)
    module.__path__ = [str(path)]
    sys.modules[name] = module
    return module


def check(condition, message):
    if not condition:
        raise AssertionError(message)


def geometry(model, kind):
    pools = model.objects if kind == "cas" else [model]
    for pool in pools:
        check(len(pool.positions) % 3 == 0, "incomplete position")
        check(all(math.isfinite(v) for v in pool.positions), "nonfinite position")
        groups = [pool] if kind == "cas" else pool.groups
        for group in groups:
            check(len(group.indices) % 3 == 0, "incomplete triangle")
            check(all(0 <= i < pool.vertices for i in group.indices), "index outside vertex pool")


def formats(args, report):
    package("v2a_source", args.addon)
    donor = package("v2a_donor", args.donor)
    sys.modules["unittransfer"] = donor
    # The donor's translation layer has application dependencies; use the same
    # English-only protocol for the reference parser, not the addon shim itself.
    shim = types.ModuleType("v2a_donor.i18n")
    shim.msg = lambda key, fallback, **values: fallback.format(**values)
    sys.modules[shim.__name__] = shim
    sys.modules["unittransfer.i18n"] = shim
    modules = {k: importlib.import_module("v2a_source.m2formats." + k)
               for k in ("mesh", "cas", "casanim", "animpack", "modelexport")}
    check("v2a_source.directories" not in sys.modules, "format import ran addon initialization")
    print("PASS format modules import without addon initialization", flush=True)
    for root in args.mod_data:
        check(root.is_dir(), "Missing mod data: " + str(root))
        packs = modules["animpack"].for_data(root)
        check(packs is not None and packs.anims and packs.skels, "Missing animation packs")
        for index in (packs.anims, packs.skels):
            check(index.to_bytes() == index.path.read_bytes(), "pack index byte round trip")
        animation = packs.animation(packs.anims.entries[0].name)
        skeleton = packs.skeleton(packs.skeleton_names()[0])
        check(animation is not None and skeleton is not None, "pack entry decode")
        check(animation.to_bytes() == packs.anims.read_entry(packs.anims.entries[0]), "packed animation byte round trip")
        check(skeleton.to_bytes() == packs.skels.read_entry(packs.skels.entries[0]), "packed skeleton byte round trip")
        loose = sorted((root / "animations").rglob("*.cas"))
        classic = next((p for p in loose if p.read_bytes()[:4] == struct.pack("<f", 3.2)), None)
        check(classic is not None, "Missing loose 3.2 animation fixture")
        anim = modules["casanim"].read_anim(classic)
        check(modules["casanim"].write_anim(anim) == classic.read_bytes(), "animation byte round trip")
        check(modules["casanim"].sample(anim, 0.0), "animation pose sample")
        print(f"PASS {root.parent.name} pack indexes round trip, packed animation/skeleton decode, loose animation round trip/sample", flush=True)
        for kind in ("mesh", "cas"):
            search = root if kind == "mesh" else root / "models_strat"
            paths = sorted(search.rglob("*." + kind))
            check(paths, "No fixtures: " + str(search))
            reader = getattr(modules[kind], "read_" + kind)
            donor_reader = getattr(importlib.import_module("v2a_donor." + kind), "read_" + kind)
            summary = dict(mod=root.parent.name, kind=kind, total=len(paths), passed=0,
                           known_unsupported=[], failures=[])
            exported = False
            for path in paths:
                try:
                    read_path = Path("\\\\?\\" + str(path.resolve())) if os.name == "nt" else path
                    model = reader(read_path)
                    geometry(model, kind)
                    if kind == "mesh" and model.vertices and not exported:
                        blob = modules["modelexport"].export_glb(model)
                        check(struct.unpack_from("<4sII", blob) == (b"glTF", 2, len(blob)), "invalid GLB header")
                        with zipfile.ZipFile(io.BytesIO(modules["modelexport"].export_obj_zip(model))) as archive:
                            obj = archive.read("model.obj").decode()
                            check(sum(line.startswith("v ") for line in obj.splitlines()) == model.vertices, "OBJ vertex count")
                            check("model.mtl" in archive.namelist(), "OBJ material missing")
                        import bpy
                        with tempfile.TemporaryDirectory(prefix="m2_glb_") as tmp:
                            glb = Path(tmp) / "smoke.glb"
                            glb.write_bytes(blob)
                            before = set(bpy.data.objects)
                            check(bpy.ops.import_scene.gltf(filepath=str(glb)) == {"FINISHED"}, "Blender GLB import")
                            imported = set(bpy.data.objects) - before
                            check(any(o.type == "MESH" and len(o.data.polygons) for o in imported), "GLB imported no triangles")
                            for obj in imported:
                                bpy.data.objects.remove(obj, do_unlink=True)
                        print(f"PASS GLB/OBJ export and Blender GLB import smoke: {path.name}", flush=True)
                        exported = True
                    summary["passed"] += 1
                except Exception as exc:
                    entry = dict(path=str(path.relative_to(root)), error=str(exc))
                    expected_error = getattr(modules[kind], "MeshError" if kind == "mesh" else "CasError")
                    try:
                        donor_reader(read_path)
                    except Exception as donor_exc:
                        if isinstance(exc, expected_error) and type(exc).__name__ == type(donor_exc).__name__ and str(exc) == str(donor_exc):
                            summary["known_unsupported"].append(entry)
                            continue
                    summary["failures"].append(entry)
            report["formats"].append(summary)
            status = "FAIL" if summary["failures"] else "PASS"
            print(f"{status} {summary['mod']} {kind}: {summary['passed']}/{len(paths)} read; "
                  f"{len(summary['known_unsupported'])} donor-confirmed unsupported; {len(summary['failures'])} unexpected", flush=True)
            for category in ("known_unsupported", "failures"):
                for entry in summary[category]:
                    print(f"  {category}: {entry['path']}: {entry['error']}", flush=True)


class Layout:
    def __getattr__(self, name):
        if name == "prop":
            return lambda data, prop, **kwargs: getattr(data, prop)
        if name == "operator":
            return lambda *args, **kwargs: types.SimpleNamespace()
        return lambda *args, **kwargs: self


def addon_settings(args, report):
    import bpy
    with tempfile.TemporaryDirectory(prefix="m2_v2a_") as folder:
        copy = Path(folder) / "v2a_addon"
        shutil.copytree(args.addon, copy, ignore=shutil.ignore_patterns("__pycache__", ".git"))
        config = copy / "text" / "directories.json"
        tree = ast.parse((copy / "directories.py").read_text())
        literal_defaults = next(n.value for n in tree.body if isinstance(n, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "DEFAULT_DIRECTORIES" for t in n.targets))
        legacy = {ast.literal_eval(k): ast.literal_eval(v) for k, v in zip(literal_defaults.keys, literal_defaults.values) if k is not None}
        legacy = {k: v for k, v in legacy.items() if not k.startswith("backend_")}
        legacy.update(directory_iwte="C:/sentinel/IWTE/", sentinel="preserved")
        config.write_text(json.dumps(legacy))
        spec = importlib.util.spec_from_file_location("v2a_addon", copy / "__init__.py", submodule_search_locations=[str(copy)])
        addon = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = addon
        spec.loader.exec_module(addon)
        addon.register()
        try:
            directories = importlib.import_module("v2a_addon.directories")
            reader = bpy.context.scene.med2_toolkit_reader
            for key in directories.DEFAULT_BACKENDS:
                check(getattr(reader, key) == directories.DEFAULT_BACKENDS[key], "legacy default " + key)
                setattr(reader, key, "BUILTIN")
                check(json.loads(config.read_text())[key] == "BUILTIN", "immediate save " + key)
                check(directories.loadBackend(key) == "BUILTIN", "reload " + key)
            addon.unregister()
            for module_name in list(sys.modules):
                if module_name == "v2a_addon" or module_name.startswith("v2a_addon."):
                    del sys.modules[module_name]
            addon = importlib.util.module_from_spec(spec)
            sys.modules[spec.name] = addon
            spec.loader.exec_module(addon)
            addon.register()
            directories = importlib.import_module("v2a_addon.directories")
            reader = bpy.context.scene.med2_toolkit_reader
            check(all(getattr(reader, key) == "BUILTIN" for key in directories.DEFAULT_BACKENDS), "fresh import did not restore saved backend")
            print("PASS fresh addon module import restores all 5 saved backends", flush=True)
            directories.saveFolderPaths()
            saved = json.loads(config.read_text())
            check(saved["sentinel"] == "preserved", "unrelated key lost")
            check(saved["directory_iwte"] == "C:/sentinel/IWTE/", "IWTE path changed")
            check(all(saved[k] == "BUILTIN" for k in directories.DEFAULT_BACKENDS), "saveFolderPaths lost backend")
            for key in directories.DEFAULT_BACKENDS:
                saved[key] = "INVALID"
            config.write_text(json.dumps(saved))
            for key in directories.DEFAULT_BACKENDS:
                check(directories.loadBackend(key) == directories.DEFAULT_BACKENDS[key], "invalid fallback " + key)
                setattr(reader, key, "IWTE")
            panels = importlib.import_module("v2a_addon.panels.multi_panel")
            draws = 0
            for mode, _label, _icon in panels.SECTIONS:
                bpy.context.scene.med2_toolkit_mode.mode_selection = mode
                for panel in panels.EMBEDDED_PANELS:
                    panel.draw(types.SimpleNamespace(layout=Layout()), bpy.context)
                    draws += 1
            print(f"PASS isolated addon registration, 5 backend round trips, IWTE path preservation, {draws} panel draws", flush=True)
            report["settings"] = {"passed": True, "panel_draws": draws}
        finally:
            addon.unregister()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--addon", type=Path, required=True)
    parser.add_argument("--donor", type=Path, required=True)
    parser.add_argument("--mod-data", type=Path, action="append", required=True)
    parser.add_argument("--settings-only", action="store_true")
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args(sys.argv[sys.argv.index("--") + 1:])
    report = {"formats": [], "settings": {"passed": False}}
    try:
        if not args.settings_only:
            formats(args, report)
        addon_settings(args, report)
    finally:
        args.report.write_text(json.dumps(report, indent=2), encoding="utf-8")
    check(not any(item["failures"] for item in report["formats"]), "Unexpected format failures; see report")
    print("PASS v2a validation", flush=True)


if __name__ == "__main__":
    main()
