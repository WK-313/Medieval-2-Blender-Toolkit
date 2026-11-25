"""Built-in import -> built-in export round trip against the original .mesh.

blender --background --factory-startup --python run_builtin_roundtrip.py -- <folder holding
Medieval-2-Toolkit-main> <game dir> <out dir> mount_barded_horse2_lod0 armoured_spearmen_lod0

Models are found in Divide_and_Conquer_EUR's modeldb by mesh file name. Each is exported twice:
with the rig's med2_single_sheet flag and without it (the modeldb lookup older rigs use).
Compares bones (casefolded), every vertex position, UVs and skin influences.
"""
import bpy, sys, os, importlib
argv = sys.argv[sys.argv.index('--') + 1:]
src, game, out = argv[0], argv[1], argv[2]
sys.path.insert(0, src)
addon = importlib.import_module('Medieval-2-Toolkit-main'); addon.register()
bi = importlib.import_module('Medieval-2-Toolkit-main.tasks.battle_import')
mesh = importlib.import_module('Medieval-2-Toolkit-main.m2formats.mesh')
data = os.path.join(game, 'mods', 'Divide_and_Conquer_EUR', 'data')
reader = bpy.context.scene.med2_toolkit_reader
reader.mods_filtered = 'custom'; reader.directory_mod_data = data; reader.directory_med2 = game
reader.directory_unit_export = out; reader.backend_battle_export = 'BUILTIN'; reader.backend_battle_import = 'BUILTIN'
units = bpy.context.scene.med2_toolkit_units; units.hide_toggle = False; units.primary_secondary = 'primary'
db = bi.modelDatabase(bi.modRoot(bpy.context))
fails = 0
for needle in argv[3:]:
    entry = next(e for e in db.entries if e.lods and needle in e.lods[0][0].lower())
    before = set(bpy.data.objects)
    bi.importModel(bpy.context, entry.name, 'rt_' + needle, '', os.path.join(out, 'import_' + needle))
    rig = next(o for o in set(bpy.data.objects) - before if o.type == 'ARMATURE')
    print('IMPORTED', entry.name, 'skeleton', rig['med2_battle_skeleton'], 'single_sheet', rig.get('med2_single_sheet'), 'attach textures', bool(entry.attach_textures))
    print('TEMPLATE', repr(rig.med2_toolkit_unit_export.iwte_task_template))
    bpy.ops.object.select_all(action='DESELECT'); rig.select_set(True); bpy.context.view_layer.objects.active = rig
    rig.med2_toolkit_unit_export.export_glb_name = 'rt_' + needle
    for flag in ([rig.get('med2_single_sheet')] + ([None] if 'med2_single_sheet' in rig else [])):
        if flag is None and 'med2_single_sheet' in rig:
            del rig['med2_single_sheet']   # an older rig: export must find it in the modeldb
        assert bpy.ops.medieval2toolkit.export_unit_glb() == {'FINISHED'}
        assert bpy.ops.medieval2toolkit.export_unit_iwte_mesh() == {'FINISHED'}
        print('TEMPLATE after', repr(rig.med2_toolkit_unit_export.iwte_task_template))
        made = mesh.read_mesh(os.path.join(out, 'rt_' + needle, 'rt_' + needle + '.mesh'))
        orig = mesh.read_mesh(bi.findDataFile(bi.modRoot(bpy.context), entry.lods[0][0], os.path.join(game, 'data')))
        def verts(m):
            res = {}
            for v in range(m.vertices):
                p = tuple(round(c, 3) for c in m.positions[v*3:v*3+3])
                w0, w1 = m.weights[v*2:v*2+2]
                inf = frozenset((m.bones[m.bone_ids[v*4+k]].casefold(), round(w, 2)) for k, w in ((2, w0), (1, w1)) if w > 0.005)
                res.setdefault(p, set()).add((round(m.uvs[v*2], 3), round(m.uvs[v*2+1], 3), inf))
            return res
        a, b = verts(orig), verts(made)
        common = set(a) & set(b)
        uvbad = sum(1 for p in common if not ({(u, v) for u, v, _ in a[p]} & {(u, v) for u, v, _ in b[p]}))
        bonebad = sum(1 for p in common if not ({i for *_, i in a[p]} & {i for *_, i in b[p]}))
        ob = [n.casefold() for n in orig.bones]; mb = [n.casefold() for n in made.bones]
        same_bones = mb == ob or (mb[:-1] == ob and mb[-1] == 'bone_weapon04')
        ok = same_bones and len(common) == len(a) and uvbad == 0 and bonebad == 0 and orig.triangles - made.triangles <= orig.triangles * 0.005
        fails += not ok
        print('ROUNDTRIP', needle, 'flag' if flag is not None else 'modeldb-lookup', 'PASS' if ok else 'FAIL',
              'bones same', same_bones,
              'tris', orig.triangles, made.triangles, 'positions matched %d/%d' % (len(common), len(a)), 'uv mismatches', uvbad, 'bone mismatches', bonebad)
print('ROUNDTRIP DONE fails', fails)
