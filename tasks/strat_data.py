"""The M2 strat map skeleton, as bone rest positions.

Taken from the empty_strat_armature_uppercase.dae / _lowercase.dae pair that
ships with the "Quick Tutorial For Strat Models w/ Blender and IWTE" guide. The
two files are the same skeleton twice - the geometry is identical to seven
decimal places and the only difference is the bone name case - so only the
uppercase spelling is stored here and the lowercase variant is produced with
armature_tools.caseConvertedName, exactly like every other case conversion in
the addon.

The heads are in armature space (the pelvis sits at the origin, the feet at
z = -0.86), which is the same rest pose the battle skeletons in the armatures
folder use: bone_head at z 0.659, bone_torso at 0.424, bone_Rfoot at -0.864 all
match Sword.glb bone for bone. That is why a battle model's meshes can simply
be re-homed onto this skeleton without moving anything.

Every bone in the .dae has an identity rotation and the same tail offset, so a
bone is fully described by its head, its parent and its tail.

The strat skeleton is the battle skeleton minus the clavicals, the jaw, the
eyebrow and the weapon groups, plus three cloak bones and the particle node the
campaign map uses to hang effects off. Anything the battle model is rigged to
that is not in this list has to be folded into the nearest bone that is, which
is what stratModel.remapOrphanGroups does.
"""

# (bone, parent or '', head in armature space, tail offset from the head)
STRAT_BONES = [
    ('bone_pelvis',        '',                 (0.0,         0.0,          0.0),        (0.0, 0.09524196, 0.0)),
    ('bone_RThigh',        'bone_pelvis',      ( 0.09523902, 8.19564e-08,  0.00075231), (0.0, 0.09524196, 0.0)),
    ('bone_Rlowerleg',     'bone_RThigh',      ( 0.1186518, -0.004995093, -0.4638515),  (0.0, 0.09524196, 0.0)),
    ('bone_Rfoot',         'bone_Rlowerleg',   ( 0.1418080, -0.01740009,  -0.8644766),  (0.0, 0.09524196, 0.0)),
    ('bone_abs',           'bone_pelvis',      (-2e-08,     -2.23517e-08,  0.2124624),  (0.0, 0.09524196, 0.0)),
    ('bone_torso',         'bone_abs',         (-0.00029457, 0.0,          0.4240205),  (0.0, 0.09524196, 0.0)),
    ('bone_head',          'bone_torso',       (-0.00035631, 0.0,          0.6589939),  (0.0, 0.09524196, 0.0)),
    ('bone_cloak_top',     'bone_torso',       ( 0.00371941, -0.2039877,   0.3396939),  (0.0, 0.09524196, 0.0)),
    ('bone_cloak_mid',     'bone_cloak_top',   ( 0.00371945, -0.2737334,   0.07939978), (0.0, 0.09524196, 0.0)),
    ('bone_cloak_bottom',  'bone_cloak_mid',   ( 0.00371950, -0.3434074,  -0.1806268),  (0.0, 0.09524196, 0.0)),
    ('bone_Rupperarm',     'bone_torso',       ( 0.1783193, -0.02390071,   0.5022484),  (0.0, 0.09524196, 0.0)),
    ('bone_Relbow',        'bone_Rupperarm',   ( 0.4805275, -0.03768679,   0.5133376),  (0.0, 0.09524196, 0.0)),
    ('bone_Rhand',         'bone_Relbow',      ( 0.7643642, -0.01133226,   0.5103310),  (0.0, 0.09524196, 0.0)),
    ('bone_Lupperarm',     'bone_torso',       (-0.1783194, -0.02390068,   0.5022483),  (0.0, 0.09524196, 0.0)),
    ('bone_Lelbow',        'bone_Lupperarm',   (-0.4805276, -0.03768676,   0.5133374),  (0.0, 0.09524196, 0.0)),
    ('bone_Lhand',         'bone_Lelbow',      (-0.7643642, -0.01133214,   0.5103309),  (0.0, 0.09524196, 0.0)),
    ('bone_LThigh',        'bone_pelvis',      (-0.09523902, 2.98023e-08,  0.00075235), (0.0, 0.09524196, 0.0)),
    ('bone_Llowerleg',     'bone_LThigh',      (-0.1186517, -0.004995219, -0.4638512),  (0.0, 0.09524196, 0.0)),
    ('bone_Lfoot',         'bone_Llowerleg',   (-0.1418078, -0.01740020,  -0.8644764),  (0.0, 0.09524196, 0.0)),
    # a root bone alongside the pelvis, not part of the body - the campaign map
    # hangs particle effects off it, and vanilla strat models all carry it
    ('Particle__View__01', '',                 (0.0,         0.0,          0.0),        (0.0, 0.5,        0.0)),
]

# Bones that carry no skin weights, so nothing should ever be folded into them.
NON_DEFORM_BONES = {'particle__view__01'}
