"""Install the built zip in an isolated Blender user directory and verify it."""
import importlib
from pathlib import Path
import sys
import zipfile

import bpy


archive, profile, source = map(Path, sys.argv[sys.argv.index("--") + 1:])
scripts = Path(bpy.utils.user_resource("SCRIPTS")).resolve()
assert scripts.is_relative_to(profile.resolve()), scripts
module_name = "Medieval-2-Toolkit-main"
with zipfile.ZipFile(archive) as package:
    names = set(package.namelist())
    for path in (source / "m2formats").glob("*"):
        if path.is_file():
            name = module_name + "/m2formats/" + path.name
            assert name in names, name
            assert package.read(name) == path.read_bytes(), name
    for relative in ("tasks/strat_reader.py", "tasks/strat_importer.py", "tasks/strat_iwte.py", "panels/strat_import_panel.py"):
        name = module_name + "/" + relative
        assert package.read(name) == (source / relative).read_bytes(), name
    assert not any("/__pycache__/" in name or "/text/" in name for name in names)
    assert not any("/assets/Saved/" in name for name in names)
print("PASS zip includes exact format files and excludes generated/user data", flush=True)

result = bpy.ops.preferences.addon_install(filepath=str(archive.resolve()))
assert result == {"FINISHED"}, result
result = bpy.ops.preferences.addon_enable(module=module_name)
assert result == {"FINISHED"}, result
try:
    addon = importlib.import_module(module_name)
    assert Path(addon.__file__).resolve().is_relative_to(scripts), addon.__file__
    directories = importlib.import_module(module_name + ".directories")
    reader = bpy.context.scene.med2_toolkit_reader
    assert all(getattr(reader, key) == directories.DEFAULT_BACKENDS[key] for key in directories.DEFAULT_BACKENDS)
    for name in ("mesh", "cas", "casanim", "animpack", "modelexport"):
        importlib.import_module(module_name + ".m2formats." + name)
    print("PASS fresh zip install, addon enable, backend defaults, and format imports", flush=True)
finally:
    bpy.ops.preferences.addon_disable(module=module_name)
print("PASS package validation", flush=True)
