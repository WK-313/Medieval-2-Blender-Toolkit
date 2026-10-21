"""Check Blender-exported bind geometry under real mesh object transforms."""
import importlib,sys,types,tempfile,math
from pathlib import Path
import bpy
from mathutils import Vector
source=next(candidate for parent in Path(__file__).resolve().parents for candidate in (parent/'Medieval-2-Toolkit-main',parent) if (candidate/'m2formats').is_dir())
p=types.ModuleType('probe');p.__path__=[str(source)];sys.modules['probe']=p
bridge=importlib.import_module('probe.tasks.battle_export')
bpy.ops.wm.read_factory_settings(use_empty=True)
arm=bpy.data.armatures.new('rig');rig=bpy.data.objects.new('rig',arm);bpy.context.collection.objects.link(rig)
bpy.context.view_layer.objects.active=rig;rig.select_set(True)
bpy.ops.object.mode_set(mode='EDIT');bone=arm.edit_bones.new('bone_pelvis');bone.head=(0,0,0);bone.tail=(0,0,1);bpy.ops.object.mode_set(mode='OBJECT')
geo=bpy.data.meshes.new('triangle');geo.from_pydata([(0,0,0),(1,0,0),(0,1,0)],[],[(0,1,2)]);geo.update()
obj=bpy.data.objects.new('Body__triangle',geo);bpy.context.collection.objects.link(obj);obj.parent=rig
uv=geo.uv_layers.new()
for loop,coord in zip(uv.data,[(0,0),(1,0),(0,1)]):loop.uv=coord
group=obj.vertex_groups.new(name='bone_pelvis');group.add([0,1,2],1,'REPLACE')
modifier=obj.modifiers.new('rig','ARMATURE');modifier.object=rig
obj.select_set(True)
with tempfile.TemporaryDirectory() as temp:
 for label,location,scale,rotation in [('identity',(0,0,0),(1,1,1),(0,0,0)),('transformed',(2,3,4),(2,3,1),(0,0,.4)),('mirrored',(0,0,0),(-1,1,1),(0,0,0))]:
  obj.location=location;obj.scale=scale;obj.rotation_euler=rotation;bpy.context.view_layer.update()
  path=Path(temp)/(label+'.glb')
  bpy.ops.export_scene.gltf(filepath=str(path),export_format='GLB',use_selection=True,export_animations=False,export_apply=True)
  result=bridge.meshFromGLB(path,['bone_pelvis'])
  expected=[]
  for v in geo.vertices:
   x,y,z=obj.matrix_world@v.co;expected.append((x,z,y))
  actual=[tuple(result.positions[i:i+3]) for i in range(0,len(result.positions),3)]
  assert len(actual)==3 and all(any(max(abs(a-b) for a,b in zip(point,target))<2e-5 for target in actual) for point in expected),(label,expected,actual)
  normal=obj.matrix_world.to_3x3().inverted().transposed()@Vector((0,0,1));normal.normalize();expected_normal=Vector((normal.x,normal.z,normal.y))
  assert all((Vector(result.normals[i:i+3])-expected_normal).length<2e-5 for i in range(0,len(result.normals),3)),label
  triangle=[Vector(actual[i]) for i in result.groups[0].indices]
  facing=(triangle[1]-triangle[0]).cross(triangle[2]-triangle[0]).dot(expected_normal)
  # Blender bakes the reflected positions but keeps the input face order.
  # The converter preserves that file; it must not guess which faces to flip.
  assert (facing<0 if label=='mirrored' else facing>0),label
  if label=='mirrored':print('SOURCE LIMITATION unapplied negative scale exports normals opposed to winding',flush=True)
  print('PASS',label,'Blender object transform preserved in game bind geometry',flush=True)
