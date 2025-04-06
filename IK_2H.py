import bpy.utils
import math

def IKGenerator(name, x, y, z):
    #Create a new armature, rename it and setup for rig generation
    obj_arm = bpy.ops.object.armature_add(enter_editmode=True, location=(x, y, z))
    obj_arm = bpy.context.view_layer.objects.active
    obj_arm.name = name + " Controller"
    arm = obj_arm.data
    arm.display_type = 'STICK'
    obj_arm.show_in_front = True
    bpy.ops.armature.select_all(action='SELECT')
    bpy.ops.armature.delete()
    
    #Collections
    arm.collections[0].name = "Med2"
    arm.collections["Med2"].is_visible = False
    arm.collections.new("IK")
    arm.collections["IK"].is_visible = False
    arm.collections.new("IK Control Bones")

    #Bone generation
    bones = {}
    bone = arm.edit_bones.new('IK Pelvis')
    bone.head = 0.0000, 0.0000, 0.0000
    bone.tail = 0.0000, 0.0000, 0.2125
    bone.roll = 0.0000
    bone.use_connect = False
    bones['IK Pelvis'] = bone.name
    arm.collections['IK Control Bones'].assign(bone)
    bone = arm.edit_bones.new('IK knee left')
    bone.head = -0.1168, 0.1438, -0.4634
    bone.tail = -0.1168, 0.4525, -0.4634
    bone.roll = 0.0000
    bone.use_connect = False
    bone.parent = arm.edit_bones[bones['IK Pelvis']]
    bones['IK knee left'] = bone.name
    arm.collections['IK Control Bones'].assign(bone)
    bone = arm.edit_bones.new('IK knee right')
    bone.head = 0.1178, 0.1351, -0.4637
    bone.tail = 0.1178, 0.4439, -0.4637
    bone.roll = 0.0000
    bone.use_connect = False
    bone.parent = arm.edit_bones[bones['IK Pelvis']]
    bones['IK knee right'] = bone.name
    arm.collections['IK Control Bones'].assign(bone)
    bone = arm.edit_bones.new('bone_pelvis')
    bone.head = 0.0000, 0.0000, 0.0000
    bone.tail = 0.0000, -0.0000, 0.0114
    bone.roll = 0.0000
    bone.use_connect = False
    bone.parent = arm.edit_bones[bones['IK Pelvis']]
    bones['bone_pelvis'] = bone.name
    arm.collections['Med2'].assign(bone)
    bone = arm.edit_bones.new('IK thigh right')
    bone.head = 0.0952, -0.0000, 0.0008
    bone.tail = 0.1178, 0.0144, -0.4637
    bone.roll = 0.0103
    bone.use_connect = False
    bone.parent = arm.edit_bones[bones['IK Pelvis']]
    bones['IK thigh right'] = bone.name
    arm.collections['IK'].assign(bone)
    bone = arm.edit_bones.new('IK calf right')
    bone.head = 0.1178, 0.0144, -0.4637
    bone.tail = 0.1420, -0.0172, -0.8632
    bone.roll = -0.0054
    bone.use_connect = True
    bone.parent = arm.edit_bones[bones['IK thigh right']]
    bones['IK calf right'] = bone.name
    arm.collections['IK'].assign(bone)
    bone = arm.edit_bones.new('bone_rlowerleg')
    bone.head = 0.1178, 0.0144, -0.4634
    bone.tail = 0.1178, 0.0144, -0.4521
    bone.roll = 0.0000
    bone.use_connect = False
    bone.parent = arm.edit_bones[bones['IK calf right']]
    bones['bone_rlowerleg'] = bone.name
    arm.collections['Med2'].assign(bone)
    bone = arm.edit_bones.new('bone_Rlowerleg')
    bone.head = 0.1178, 0.0144, -0.4637
    bone.tail = 0.1178, 0.0144, -0.4524
    bone.roll = 0.0000
    bone.use_connect = False
    bone.parent = arm.edit_bones[bones['IK calf right']]
    bones['bone_Rlowerleg'] = bone.name
    arm.collections['Med2'].assign(bone)
    bone = arm.edit_bones.new('bone_rthigh')
    bone.head = 0.0952, 0.0000, 0.0008
    bone.tail = 0.0952, -0.0000, 0.0122
    bone.roll = 0.0000
    bone.use_connect = False
    bone.parent = arm.edit_bones[bones['IK thigh right']]
    bones['bone_rthigh'] = bone.name
    arm.collections['Med2'].assign(bone)
    bone = arm.edit_bones.new('bone_RThigh')
    bone.head = 0.0952, 0.0000, 0.0008
    bone.tail = 0.0952, -0.0000, 0.0122
    bone.roll = 0.0000
    bone.use_connect = False
    bone.parent = arm.edit_bones[bones['IK thigh right']]
    bones['bone_RThigh'] = bone.name
    arm.collections['Med2'].assign(bone)
    bone = arm.edit_bones.new('IK thigh left')
    bone.head = -0.0952, 0.0000, 0.0008
    bone.tail = -0.1168, 0.0231, -0.4634
    bone.roll = -0.0088
    bone.use_connect = False
    bone.parent = arm.edit_bones[bones['IK Pelvis']]
    bones['IK thigh left'] = bone.name
    arm.collections['IK'].assign(bone)
    bone = arm.edit_bones.new('IK calf left')
    bone.head = -0.1168, 0.0231, -0.4634
    bone.tail = -0.1419, -0.0175, -0.8620
    bone.roll = 0.0125
    bone.use_connect = True
    bone.parent = arm.edit_bones[bones['IK thigh left']]
    bones['IK calf left'] = bone.name
    arm.collections['IK'].assign(bone)
    bone = arm.edit_bones.new('bone_llowerleg')
    bone.head = -0.1168, 0.0231, -0.4634
    bone.tail = -0.1168, 0.0231, -0.4521
    bone.roll = 0.0000
    bone.use_connect = False
    bone.parent = arm.edit_bones[bones['IK calf left']]
    bones['bone_llowerleg'] = bone.name
    arm.collections['Med2'].assign(bone)
    bone = arm.edit_bones.new('bone_Llowerleg')
    bone.head = -0.1168, 0.0231, -0.4634
    bone.tail = -0.1168, 0.0231, -0.4521
    bone.roll = 0.0000
    bone.use_connect = False
    bone.parent = arm.edit_bones[bones['IK calf left']]
    bones['bone_Llowerleg'] = bone.name
    arm.collections['Med2'].assign(bone)
    bone = arm.edit_bones.new('bone_lthigh')
    bone.head = -0.0952, 0.0000, 0.0008
    bone.tail = -0.0952, -0.0000, 0.0122
    bone.roll = 0.0000
    bone.use_connect = False
    bone.parent = arm.edit_bones[bones['IK thigh left']]
    bones['bone_lthigh'] = bone.name
    arm.collections['Med2'].assign(bone)
    bone = arm.edit_bones.new('bone_LThigh')
    bone.head = -0.0952, 0.0000, 0.0008
    bone.tail = -0.0952, -0.0000, 0.0122
    bone.roll = 0.0000
    bone.use_connect = False
    bone.parent = arm.edit_bones[bones['IK thigh left']]
    bones['bone_LThigh'] = bone.name
    arm.collections['Med2'].assign(bone)
    bone = arm.edit_bones.new('IK Abs')
    bone.head = 0.0000, 0.0000, 0.2125
    bone.tail = 0.0000, 0.0000, 0.4240
    bone.roll = 0.0000
    bone.use_connect = True
    bone.parent = arm.edit_bones[bones['IK Pelvis']]
    bones['IK Abs'] = bone.name
    arm.collections['IK'].assign(bone)
    bone = arm.edit_bones.new('bone_abs')
    bone.head = 0.0000, 0.0000, 0.2125
    bone.tail = 0.0000, -0.0000, 0.2239
    bone.roll = 0.0000
    bone.use_connect = False
    bone.parent = arm.edit_bones[bones['IK Abs']]
    bones['bone_abs'] = bone.name
    arm.collections['Med2'].assign(bone)
    bone = arm.edit_bones.new('IK Torso')
    bone.head = 0.0000, 0.0000, 0.4240
    bone.tail = 0.0000, 0.0000, 0.5540
    bone.roll = 0.0000
    bone.use_connect = True
    bone.parent = arm.edit_bones[bones['IK Abs']]
    bones['IK Torso'] = bone.name
    arm.collections['IK'].assign(bone)
    bone = arm.edit_bones.new('bone_torso')
    bone.head = -0.0003, 0.0000, 0.4240
    bone.tail = -0.0003, -0.0000, 0.4354
    bone.roll = 0.0000
    bone.use_connect = False
    bone.parent = arm.edit_bones[bones['IK Torso']]
    bones['bone_torso'] = bone.name
    arm.collections['Med2'].assign(bone)
    bone = arm.edit_bones.new('bone_rclavical')
    bone.head = 0.0130, -0.0274, 0.5540
    bone.tail = 0.0130, -0.0274, 0.5654
    bone.roll = 0.0000
    bone.use_connect = False
    bone.parent = arm.edit_bones[bones['bone_torso']]
    bones['bone_rclavical'] = bone.name
    arm.collections['Med2'].assign(bone)
    bone = arm.edit_bones.new('bone_lclavical')
    bone.head = -0.0105, -0.0274, 0.5540
    bone.tail = -0.0105, -0.0274, 0.5654
    bone.roll = 0.0000
    bone.use_connect = False
    bone.parent = arm.edit_bones[bones['bone_torso']]
    bones['bone_lclavical'] = bone.name
    arm.collections['Med2'].assign(bone)
    bone = arm.edit_bones.new('bone_Rclavical')
    bone.head = 0.0130, -0.0274, 0.5540
    bone.tail = 0.0130, -0.0274, 0.5654
    bone.roll = 0.0000
    bone.use_connect = False
    bone.parent = arm.edit_bones[bones['bone_torso']]
    bones['bone_Rclavical'] = bone.name
    arm.collections['Med2'].assign(bone)
    bone = arm.edit_bones.new('bone_Lclavical')
    bone.head = -0.0105, -0.0274, 0.5540
    bone.tail = -0.0105, -0.0274, 0.5654
    bone.roll = 0.0000
    bone.use_connect = False
    bone.parent = arm.edit_bones[bones['bone_torso']]
    bones['bone_Lclavical'] = bone.name
    arm.collections['Med2'].assign(bone)
    bone = arm.edit_bones.new('IK frist  left')
    bone.head = -0.7643, -0.0116, 0.5102
    bone.tail = -0.7643, 0.2971, 0.5102
    bone.roll = 0.0000
    bone.use_connect = False
    bone.parent = arm.edit_bones[bones['IK Torso']]
    bones['IK frist  left'] = bone.name
    arm.collections['IK Control Bones'].assign(bone)
    bone = arm.edit_bones.new('bone_lhand')
    bone.head = -0.7643, -0.0116, 0.5102
    bone.tail = -0.7643, -0.0116, 0.5215
    bone.roll = 0.0000
    bone.use_connect = False
    bone.parent = arm.edit_bones[bones['IK frist  left']]
    bones['bone_lhand'] = bone.name
    arm.collections['Med2'].assign(bone)
    bone = arm.edit_bones.new('bone_bowoffset')
    bone.head = -0.7643, -0.0116, 0.4902
    bone.tail = -0.7643, -0.0116, 0.5015
    bone.roll = 0.0000
    bone.use_connect = False
    bone.parent = arm.edit_bones[bones['bone_lhand']]
    bones['bone_bowoffset'] = bone.name
    arm.collections['Med2'].assign(bone)
    bone = arm.edit_bones.new('bone_Weapon01')
    bone.head = -0.8404, -0.0113, 0.4932
    bone.tail = -0.8404, -0.0113, 0.5045
    bone.roll = 0.0000
    bone.use_connect = False
    bone.parent = arm.edit_bones[bones['bone_lhand']]
    bones['bone_Weapon01'] = bone.name
    arm.collections['Med2'].assign(bone)
    bone = arm.edit_bones.new('bone_Weapon02')
    bone.head = -1.0317, -0.0113, 0.5416
    bone.tail = -1.0317, -0.0113, 0.5529
    bone.roll = 0.0000
    bone.use_connect = False
    bone.parent = arm.edit_bones[bones['bone_Weapon01']]
    bones['bone_Weapon02'] = bone.name
    arm.collections['Med2'].assign(bone)
    bone = arm.edit_bones.new('bone_weapon_group03')
    bone.head = -0.7643, -0.0116, 0.5102
    bone.tail = -0.7643, -0.0116, 0.5215
    bone.roll = 0.0000
    bone.use_connect = False
    bone.parent = arm.edit_bones[bones['bone_lhand']]
    bones['bone_weapon_group03'] = bone.name
    arm.collections['Med2'].assign(bone)
    bone = arm.edit_bones.new('bone_bowstring')
    bone.head = -0.5303, -0.0116, 0.4902
    bone.tail = -0.5303, -0.0116, 0.5015
    bone.roll = 0.0000
    bone.use_connect = False
    bone.parent = arm.edit_bones[bones['IK frist  left']]
    bones['bone_bowstring'] = bone.name
    arm.collections['Med2'].assign(bone)
    bone = arm.edit_bones.new('bone_Lhand')
    bone.head = -0.7643, -0.0116, 0.5102
    bone.tail = -0.7643, -0.0116, 0.5215
    bone.roll = 0.0000
    bone.use_connect = False
    bone.parent = arm.edit_bones[bones['IK frist  left']]
    bones['bone_Lhand'] = bone.name
    arm.collections['Med2'].assign(bone)
    bone = arm.edit_bones.new('bone_shield')
    bone.head = -0.7366, -0.2586, 0.5904
    bone.tail = -0.7366, -0.2586, 0.6018
    bone.roll = 0.0000
    bone.use_connect = False
    bone.parent = arm.edit_bones[bones['bone_Lhand']]
    bones['bone_shield'] = bone.name
    arm.collections['Med2'].assign(bone)
    bone = arm.edit_bones.new('IK frist right')
    bone.head = 0.7644, -0.0113, 0.5103
    bone.tail = 0.7644, 0.2974, 0.5103
    bone.roll = 0.0000
    bone.use_connect = False
    bone.parent = arm.edit_bones[bones['IK Torso']]
    bones['IK frist right'] = bone.name
    arm.collections['IK Control Bones'].assign(bone)
    bone = arm.edit_bones.new('bone_rhand')
    bone.head = 0.7644, -0.0113, 0.5103
    bone.tail = 0.7644, -0.0113, 0.5216
    bone.roll = 0.0000
    bone.use_connect = False
    bone.parent = arm.edit_bones[bones['IK frist right']]
    bones['bone_rhand'] = bone.name
    arm.collections['Med2'].assign(bone)
    bone = arm.edit_bones.new('bone_sling')
    bone.head = 0.8844, -0.0113, 0.5103
    bone.tail = 0.8844, -0.0113, 0.5216
    bone.roll = 0.0000
    bone.use_connect = False
    bone.parent = arm.edit_bones[bones['bone_rhand']]
    bones['bone_sling'] = bone.name
    arm.collections['Med2'].assign(bone)
    bone = arm.edit_bones.new('bone_weapon_group01')
    bone.head = 0.7644, -0.0113, 0.5103
    bone.tail = 0.7644, -0.0113, 0.5216
    bone.roll = 0.0000
    bone.use_connect = False
    bone.parent = arm.edit_bones[bones['bone_rhand']]
    bones['bone_weapon_group01'] = bone.name
    arm.collections['Med2'].assign(bone)
    bone = arm.edit_bones.new('bone_Rhand')
    bone.head = 0.7644, -0.0113, 0.5103
    bone.tail = 0.7644, -0.0113, 0.5216
    bone.roll = 0.0000
    bone.use_connect = False
    bone.parent = arm.edit_bones[bones['IK frist right']]
    bones['bone_Rhand'] = bone.name
    arm.collections['Med2'].assign(bone)
    bone = arm.edit_bones.new('bone_weapon01')
    bone.head = 0.8491, -0.0113, 0.4874
    bone.tail = 0.8491, -0.0113, 0.4987
    bone.roll = 0.0000
    bone.use_connect = False
    bone.parent = arm.edit_bones[bones['bone_Rhand']]
    bones['bone_weapon01'] = bone.name
    arm.collections['Med2'].assign(bone)
    bone = arm.edit_bones.new('bone_weapon_group02')
    bone.head = 0.8491, -0.0113, 0.4874
    bone.tail = 0.8491, -0.0113, 0.4987
    bone.roll = 0.0000
    bone.use_connect = False
    bone.parent = arm.edit_bones[bones['bone_weapon01']]
    bones['bone_weapon_group02'] = bone.name
    arm.collections['Med2'].assign(bone)
    bone = arm.edit_bones.new('Pole')
    bone.head = 0.9488, -0.0113, 0.5103
    bone.tail = 0.9488, 0.3711, 0.5103
    bone.roll = 0.0000
    bone.use_connect = False
    bone.parent = arm.edit_bones[bones['IK frist right']]
    bones['Pole'] = bone.name
    arm.collections['IK Control Bones'].assign(bone)
    bone = arm.edit_bones.new('IK elbow left')
    bone.head = -0.4805, -0.2584, 0.5134
    bone.tail = -0.4805, -0.5671, 0.5134
    bone.roll = -1.5708
    bone.use_connect = False
    bone.parent = arm.edit_bones[bones['IK Torso']]
    bones['IK elbow left'] = bone.name
    arm.collections['IK Control Bones'].assign(bone)
    bone = arm.edit_bones.new('IK elbow right')
    bone.head = 0.4805, -0.2577, 0.5134
    bone.tail = 0.4805, -0.5665, 0.5134
    bone.roll = -1.5708
    bone.use_connect = False
    bone.parent = arm.edit_bones[bones['IK Torso']]
    bones['IK elbow right'] = bone.name
    arm.collections['IK Control Bones'].assign(bone)
    bone = arm.edit_bones.new('IK upper arm right')
    bone.head = 0.1783, -0.0239, 0.5022
    bone.tail = 0.4805, -0.0377, 0.5134
    bone.roll = 0.0000
    bone.use_connect = False
    bone.parent = arm.edit_bones[bones['IK Torso']]
    bones['IK upper arm right'] = bone.name
    arm.collections['IK'].assign(bone)
    bone = arm.edit_bones.new('IK lower arm right')
    bone.head = 0.4805, -0.0377, 0.5134
    bone.tail = 0.7644, -0.0113, 0.5103
    bone.roll = 0.0465
    bone.use_connect = True
    bone.parent = arm.edit_bones[bones['IK upper arm right']]
    bones['IK lower arm right'] = bone.name
    arm.collections['IK'].assign(bone)
    bone = arm.edit_bones.new('bone_relbow')
    bone.head = 0.4805, -0.0377, 0.5134
    bone.tail = 0.4805, -0.0377, 0.5248
    bone.roll = 0.0000
    bone.use_connect = False
    bone.parent = arm.edit_bones[bones['IK lower arm right']]
    bones['bone_relbow'] = bone.name
    arm.collections['Med2'].assign(bone)
    bone = arm.edit_bones.new('bone_Relbow')
    bone.head = 0.4805, -0.0377, 0.5134
    bone.tail = 0.4805, -0.0377, 0.5248
    bone.roll = 0.0000
    bone.use_connect = False
    bone.parent = arm.edit_bones[bones['IK lower arm right']]
    bones['bone_Relbow'] = bone.name
    arm.collections['Med2'].assign(bone)
    bone = arm.edit_bones.new('bone_rupperarm')
    bone.head = 0.1783, -0.0239, 0.5022
    bone.tail = 0.1783, -0.0239, 0.5136
    bone.roll = 0.0000
    bone.use_connect = False
    bone.parent = arm.edit_bones[bones['IK upper arm right']]
    bones['bone_rupperarm'] = bone.name
    arm.collections['Med2'].assign(bone)
    bone = arm.edit_bones.new('bone_Rupperarm')
    bone.head = 0.1783, -0.0239, 0.5022
    bone.tail = 0.1783, -0.0239, 0.5136
    bone.roll = 0.0000
    bone.use_connect = False
    bone.parent = arm.edit_bones[bones['IK upper arm right']]
    bones['bone_Rupperarm'] = bone.name
    arm.collections['Med2'].assign(bone)
    bone = arm.edit_bones.new('IK upper arm left')
    bone.head = -0.1783, -0.0239, 0.5022
    bone.tail = -0.4805, -0.0383, 0.5134
    bone.roll = 0.0000
    bone.use_connect = False
    bone.parent = arm.edit_bones[bones['IK Torso']]
    bones['IK upper arm left'] = bone.name
    arm.collections['IK'].assign(bone)
    bone = arm.edit_bones.new('IK lower arm left')
    bone.head = -0.4805, -0.0383, 0.5134
    bone.tail = -0.7643, -0.0116, 0.5102
    bone.roll = -0.0472
    bone.use_connect = True
    bone.parent = arm.edit_bones[bones['IK upper arm left']]
    bones['IK lower arm left'] = bone.name
    arm.collections['IK'].assign(bone)
    bone = arm.edit_bones.new('bone_lelbow')
    bone.head = -0.4805, -0.0383, 0.5134
    bone.tail = -0.4805, -0.0383, 0.5247
    bone.roll = 0.0000
    bone.use_connect = False
    bone.parent = arm.edit_bones[bones['IK lower arm left']]
    bones['bone_lelbow'] = bone.name
    arm.collections['Med2'].assign(bone)
    bone = arm.edit_bones.new('bone_Lelbow')
    bone.head = -0.4805, -0.0383, 0.5134
    bone.tail = -0.4805, -0.0383, 0.5247
    bone.roll = 0.0000
    bone.use_connect = False
    bone.parent = arm.edit_bones[bones['IK lower arm left']]
    bones['bone_Lelbow'] = bone.name
    arm.collections['Med2'].assign(bone)
    bone = arm.edit_bones.new('bone_lupperarm')
    bone.head = -0.1783, -0.0239, 0.5022
    bone.tail = -0.1783, -0.0239, 0.5136
    bone.roll = 0.0000
    bone.use_connect = False
    bone.parent = arm.edit_bones[bones['IK upper arm left']]
    bones['bone_lupperarm'] = bone.name
    arm.collections['Med2'].assign(bone)
    bone = arm.edit_bones.new('bone_Lupperarm')
    bone.head = -0.1783, -0.0239, 0.5022
    bone.tail = -0.1783, -0.0239, 0.5136
    bone.roll = 0.0000
    bone.use_connect = False
    bone.parent = arm.edit_bones[bones['IK upper arm left']]
    bones['bone_Lupperarm'] = bone.name
    arm.collections['Med2'].assign(bone)
    bone = arm.edit_bones.new('IK Head')
    bone.head = -0.0004, 0.0000, 0.6590
    bone.tail = -0.0004, 0.0984, 0.6590
    bone.roll = 0.0000
    bone.use_connect = False
    bone.parent = arm.edit_bones[bones['IK Torso']]
    bones['IK Head'] = bone.name
    arm.collections['IK Control Bones'].assign(bone)
    bone = arm.edit_bones.new('bone_head')
    bone.head = -0.0004, 0.0000, 0.6590
    bone.tail = -0.0004, -0.0000, 0.6704
    bone.roll = 0.0000
    bone.use_connect = False
    bone.parent = arm.edit_bones[bones['IK Head']]
    bones['bone_head'] = bone.name
    arm.collections['Med2'].assign(bone)
    bone = arm.edit_bones.new('bone_jaw')
    bone.head = 0.0000, -0.0034, 0.6698
    bone.tail = 0.0000, -0.0034, 0.6811
    bone.roll = 0.0000
    bone.use_connect = False
    bone.parent = arm.edit_bones[bones['bone_head']]
    bones['bone_jaw'] = bone.name
    arm.collections['Med2'].assign(bone)
    bone = arm.edit_bones.new('bone_eyebrow')
    bone.head = 0.0013, -0.0745, 0.7768
    bone.tail = 0.0013, -0.0745, 0.7882
    bone.roll = 0.0000
    bone.use_connect = False
    bone.parent = arm.edit_bones[bones['bone_head']]
    bones['bone_eyebrow'] = bone.name
    arm.collections['Med2'].assign(bone)
    bone = arm.edit_bones.new('IK Torso Controller')
    bone.head = 0.0000, 0.0000, 0.6057
    bone.tail = 0.0000, 0.1970, 0.6057
    bone.roll = 0.0000
    bone.use_connect = False
    bone.parent = arm.edit_bones[bones['IK Pelvis']]
    bones['IK Torso Controller'] = bone.name
    arm.collections['IK Control Bones'].assign(bone)
    bone = arm.edit_bones.new('IK angle left')
    bone.head = -0.1419, -0.0175, -0.8620
    bone.tail = -0.1419, 0.2912, -0.8620
    bone.roll = 0.0000
    bone.use_connect = False
    bones['IK angle left'] = bone.name
    arm.collections['IK Control Bones'].assign(bone)
    bone = arm.edit_bones.new('bone_lfoot')
    bone.head = -0.1419, -0.0175, -0.8620
    bone.tail = -0.1419, -0.0175, -0.8507
    bone.roll = 0.0000
    bone.use_connect = False
    bone.parent = arm.edit_bones[bones['IK angle left']]
    bones['bone_lfoot'] = bone.name
    arm.collections['Med2'].assign(bone)
    bone = arm.edit_bones.new('bone_Lfoot')
    bone.head = -0.1419, -0.0175, -0.8620
    bone.tail = -0.1419, -0.0175, -0.8507
    bone.roll = 0.0000
    bone.use_connect = False
    bone.parent = arm.edit_bones[bones['IK angle left']]
    bones['bone_Lfoot'] = bone.name
    arm.collections['Med2'].assign(bone)
    bone = arm.edit_bones.new('IK angle right')
    bone.head = 0.1420, -0.0172, -0.8632
    bone.tail = 0.1420, 0.2915, -0.8632
    bone.roll = 0.0000
    bone.use_connect = False
    bones['IK angle right'] = bone.name
    arm.collections['IK Control Bones'].assign(bone)
    bone = arm.edit_bones.new('bone_rfoot')
    bone.head = 0.1420, -0.0172, -0.8620
    bone.tail = 0.1420, -0.0172, -0.8507
    bone.roll = 0.0000
    bone.use_connect = False
    bone.parent = arm.edit_bones[bones['IK angle right']]
    bones['bone_rfoot'] = bone.name
    arm.collections['Med2'].assign(bone)
    bone = arm.edit_bones.new('bone_Rfoot')
    bone.head = 0.1420, -0.0172, -0.8632
    bone.tail = 0.1420, -0.0172, -0.8519
    bone.roll = 0.0000
    bone.use_connect = False
    bone.parent = arm.edit_bones[bones['IK angle right']]
    bones['bone_Rfoot'] = bone.name
    arm.collections['Med2'].assign(bone)
    bone = arm.edit_bones.new('Switch')
    bone.head = -0.5834, 0.1166, 0.0500
    bone.tail = -0.5834, 0.1166, 0.3262
    bone.roll = 0.0000
    bone.use_connect = False
    bones['Switch'] = bone.name
    arm.collections['IK Control Bones'].assign(bone)


    #Swap to pose mode to setup the constraints and drivers
    bpy.ops.object.mode_set(mode='POSE',toggle=True)

    pbone = obj_arm.pose.bones['IK calf right']
    cons = pbone.constraints.new('IK')
    cons.target = bpy.data.objects[obj_arm.name]
    cons.subtarget = "IK angle right"
    cons.pole_target = bpy.data.objects[obj_arm.name]
    cons.pole_subtarget = "IK knee right"
    cons.chain_count = 2
    cons.pole_angle = math.pi/2

    pbone = obj_arm.pose.bones['IK calf left']
    cons = pbone.constraints.new('IK')
    cons.target = bpy.data.objects[obj_arm.name]
    cons.subtarget = "IK angle left"
    cons.pole_target = bpy.data.objects[obj_arm.name]
    cons.pole_subtarget = "IK knee left"
    cons.chain_count = 2
    cons.pole_angle = math.pi/2

    pbone = obj_arm.pose.bones['IK Torso']
    cons = pbone.constraints.new('IK')
    cons.target = bpy.data.objects[obj_arm.name]
    cons.subtarget = "IK Torso Controller"
    cons.chain_count = 2

    pbone = obj_arm.pose.bones['IK Torso']
    cons = pbone.constraints.new('COPY_ROTATION')
    cons.target = bpy.data.objects[obj_arm.name]
    cons.subtarget = "IK Torso Controller"

    pbone = obj_arm.pose.bones['IK frist  left']
    cons = pbone.constraints.new('COPY_LOCATION')
    cons.target = bpy.data.objects[obj_arm.name]
    cons.subtarget = "Pole"
    cons.head_tail = 1
    fcurve = obj_arm.driver_add('pose.bones["IK frist  left"].constraints["Copy Location"].influence')
    drv = fcurve.driver
    drv.type = 'SCRIPTED'
    drv.expression = "1 if (var > 0) else 0"
    variable = drv.variables.new()
    variable.name = "var"
    variable.type = 'TRANSFORMS'
    variable.targets[0].id = bpy.data.objects[obj_arm.name]
    variable.targets[0].bone_target = "Switch"
    variable.targets[0].transform_type = 'LOC_Y'
    variable.targets[0].transform_space = 'TRANSFORM_SPACE'

    pbone = obj_arm.pose.bones['IK frist  left']
    cons = pbone.constraints.new('COPY_ROTATION')
    cons.target = bpy.data.objects[obj_arm.name]
    cons.subtarget = "Pole"
    fcurve = obj_arm.driver_add('pose.bones["IK frist  left"].constraints["Copy Rotation"].influence')
    drv = fcurve.driver
    drv.type = 'SCRIPTED'
    drv.expression = "1 if (var > 0) else 0"
    variable = drv.variables.new()
    variable.name = "var"
    variable.type = 'TRANSFORMS'
    variable.targets[0].id = bpy.data.objects[obj_arm.name]
    variable.targets[0].bone_target = "Switch"
    variable.targets[0].transform_type = 'LOC_Y'
    variable.targets[0].transform_space = 'TRANSFORM_SPACE'

    pbone = obj_arm.pose.bones['IK lower arm right']
    cons = pbone.constraints.new('IK')
    cons.target = bpy.data.objects[obj_arm.name]
    cons.subtarget = "IK frist right"
    cons.pole_target = bpy.data.objects[obj_arm.name]
    cons.pole_subtarget = "IK elbow right"
    cons.chain_count = 2
    cons.pole_angle = 0

    pbone = obj_arm.pose.bones['IK lower arm left']
    cons = pbone.constraints.new('IK')
    cons.target = bpy.data.objects[obj_arm.name]
    cons.subtarget = "IK frist  left"
    cons.pole_target = bpy.data.objects[obj_arm.name]
    cons.pole_subtarget = "IK elbow left"
    cons.chain_count = 2
    cons.pole_angle = math.pi

    pbone = obj_arm.pose.bones['IK Head']
    cons = pbone.constraints.new('LIMIT_ROTATION')
    cons.use_limit_x = True
    cons.min_x = -0.959931
    cons.max_x = 0.436332
    cons.use_limit_y = True
    cons.min_y = -0.785398
    cons.max_y = 0.785398
    cons.use_limit_z = True
    cons.min_z = -1.39626
    cons.max_z = 1.39626
    cons.owner_space = 'LOCAL'

    pbone = obj_arm.pose.bones['IK Torso Controller']
    cons = pbone.constraints.new('LIMIT_ROTATION')
    cons.use_limit_x = True
    cons.min_x = 0
    cons.max_x = 0
    cons.use_limit_y = True
    cons.min_y = 0
    cons.max_y = 0
    cons.use_limit_z = True
    cons.min_z = -math.pi/2
    cons.max_z = math.pi/2
    cons.owner_space = 'LOCAL'

    pbone = obj_arm.pose.bones['Switch']
    pbone.lock_location[0] = True
    pbone.lock_location[2] = True
    cons = pbone.constraints.new('LIMIT_LOCATION')
    cons.use_min_y = True
    cons.use_max_y = True
    cons.min_y = -0.05
    cons.max_y = 0.05
    cons.owner_space = 'LOCAL'

    #Finish by returning to object mode
    bpy.ops.object.mode_set(mode='OBJECT',toggle=True)
    print("Finished creating the controller")
    return(obj_arm)