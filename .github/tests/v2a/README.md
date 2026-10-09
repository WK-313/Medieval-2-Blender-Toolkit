# Format-layer validation

Run from the repository root with Blender 5.1 or newer. The format sweep reads
real game assets without changing them. It compares parser refusals against the
shared Unit Transfer source, checks geometry, round-trips animation data, and
imports a generated GLB into Blender. Settings tests use a temporary addon copy.

```powershell
$blender = 'D:\Blender-5.1.2\blender.exe'
$donor = 'D:\College\Coding 2\Unit Transfer\main\unittransfer'
$mods = 'C:\Program Files (x86)\Steam\steamapps\common\Medieval II Total War\mods'
& $blender --background --factory-startup --python-exit-code 1 --python .github/tests/v2a/run_blender.py -- --addon . --donor $donor --mod-data "$mods/Divide_and_Conquer_EUR/data" --mod-data "$mods/Third_Age_Reforged/data" --report v2a-results.json
```

Change the paths for your installation. Add `--settings-only` after `--` to run
registration, backend persistence, and panel checks without scanning the assets.
The report records each fixture and distinguishes donor-confirmed unsupported
files from unexpected failures. Fixture totals depend on the installed mod versions.

To verify a built addon zip, start Blender with separate user directories:

```powershell
$profile = Join-Path $env:TEMP ('m2-v2a-package-' + [guid]::NewGuid())
$env:BLENDER_USER_SCRIPTS = Join-Path $profile 'scripts'
$env:BLENDER_USER_CONFIG = Join-Path $profile 'config'
$env:BLENDER_USER_DATAFILES = Join-Path $profile 'datafiles'
New-Item -ItemType Directory -Force $env:BLENDER_USER_SCRIPTS, $env:BLENDER_USER_CONFIG, $env:BLENDER_USER_DATAFILES | Out-Null
& $blender --background --factory-startup --python-exit-code 1 --python .github/tests/v2a/check_package.py -- /path/to/Medieval-2-Toolkit.zip $profile .
```

The package check verifies the vendored files byte for byte, installs the zip in
that temporary profile, enables the addon, and checks fresh IWTE defaults.
These scripts live under `.github` so they are excluded from the addon package.
