"""Game animation sources and Blender Actions, using the shared format engine.

The CAS/viewer skin transform is pose @ inverse(translation-only bind).
Conjugate it through the IWTE CAS-to-Blender Y/Z reflection, then apply it to
each Blender rest bone. This supports the bundled rigs' different bone rolls
without changing the skeleton or its mesh bind pose.
"""
import hashlib
import json
import math
from pathlib import Path
import struct

import bpy
from mathutils import Matrix, Quaternion, Vector

from ..m2formats import animpack, casanim


CAS_TO_BLENDER = Matrix(((1, 0, 0, 0), (0, 0, 1, 0),
                         (0, 1, 0, 0), (0, 0, 0, 1)))


def _roots(data_dir):
    root = Path(data_dir)
    roots = [root]
    if root.parent.parent.name.casefold() == 'mods':
        roots.append(root.parent.parent.parent / 'data')
    return roots


def loadAnimation(data_dir, skeleton, *, action=None, path=None, slot=None):
    """Resolve a descriptor action, packed slot or explicit game animation path.

    A loose override wins. Packed bytes, including unpacked pack entries, use
    the named skeleton's bone table; they are never guessed from another rig.
    Reads the packs in place and never extracts or edits game files.
    """
    if sum(value is not None for value in (action, path, slot)) != 1:
        raise ValueError('Choose one animation action, path or slot')
    roots = _roots(data_dir)
    packs, origin = animpack.packs_for(roots[0])
    packed_skeleton = packs.skeleton(skeleton) if packs else None
    if packed_skeleton and (not math.isfinite(packed_skeleton.scale) or packed_skeleton.scale <= 0):
        raise casanim.AnimError('Packed skeleton has an invalid scale')
    if slot is not None:
        if not isinstance(slot, int) or packed_skeleton is None or not 0 <= slot < len(packed_skeleton.slots):
            raise casanim.AnimError('The named packed skeleton has no such animation slot')
        selected = packed_skeleton.slots[slot]
        if selected is None:
            raise casanim.AnimError('The selected animation slot is empty')
        path = selected.path
    elif action is not None:
        descriptor = next((types[skeleton.casefold()] for root in roots
                           if (types := casanim.skeleton_types(root)).get(skeleton.casefold())), None)
        if descriptor is None:
            raise casanim.AnimError('Skeleton not found in descr_skeleton.txt: %s' % skeleton)
        paths = {}
        for name, candidate in descriptor.anims:
            if name.casefold() == action.casefold():
                paths.setdefault(candidate.replace('\\', '/').casefold(), candidate)
        if len(paths) != 1:
            raise casanim.AnimError('Animation action is missing or ambiguous: %s; choose an explicit path' % action)
        path = next(iter(paths.values()))
    if not path:
        raise casanim.AnimError('The animation path is empty')
    # A vanilla loose file must not replace this mod's packed animation.
    loose_roots = roots[:1] if origin == 'mod' else roots
    for root in loose_roots:
        hit, _how = casanim.find(root, path)
        if hit is None:
            continue
        data = hit.read_bytes()
        if casanim.packed_counts(data) is None:
            result = casanim.read_anim_bytes(data, str(hit))
        else:
            bones = packed_skeleton.bone_table() if packed_skeleton else casanim.skeleton_bones(root, skeleton)
            if bones is None:
                raise casanim.AnimError('Unpacked animation needs its named skeleton: %s' % skeleton)
            result = casanim.read_packed_bytes(data, str(hit), bones, skeleton)
        result.med2_source_kind = 'loose' if casanim.packed_counts(data) is None else 'unpacked'
        break
    else:
        if packs is None or packs.anims is None or packed_skeleton is None:
            raise casanim.AnimError('No loose animation or named animation pack found: %s' % path)
        entry = animpack.resolve_slot(packs.anims, path, packed_skeleton.scale)
        if entry is None:
            raise casanim.AnimError('Animation not found in the pack: %s' % path)
        result = casanim.read_packed_bytes(packs.anims.read_entry(entry), path,
                                          packed_skeleton.bone_table(), skeleton)
        # Packed pivots belong to the skeleton scale. Keys may come from the
        # smallest available scale when the pack has no exact-scale entry.
        if not math.isfinite(entry.scale) or entry.scale <= 0:
            raise casanim.AnimError('Packed animation has an invalid scale')
        ratio = packed_skeleton.scale / entry.scale
        if abs(ratio - 1.0) > 1e-6:
            for track in result.tracks:
                # Position offsets were decoded against skeleton pivots;
                # rescale the absolute keyed positions, then subtract pivots.
                for i in range(len(track.pos)):
                    pivot = track.pivot[i % 3]
                    track.pos[i] = (track.pos[i] + pivot) * ratio - pivot
        result.med2_source_kind = origin + '-pack'
    result.med2_skeleton = skeleton
    return result


def _nameKey(name):
    return name.casefold().replace('_', '').replace(' ', '')


def _validate(animation):
    if not animation.tracks:
        raise ValueError('The animation has no bone tracks')
    times = list(animation.key_times)
    if not math.isfinite(animation.length) or animation.length < 0:
        raise ValueError('The animation has an invalid duration')
    if (times and abs(times[0]) > 1e-6) or any(not math.isfinite(t) or t < 0 for t in times) or any(b <= a for a, b in zip(times, times[1:])):
        raise ValueError('Animation times must start at zero, be finite and strictly increasing')
    names = set()
    for i, track in enumerate(animation.tracks):
        key = _nameKey(track.name)
        if not key or key in names:
            raise ValueError('Animation bone names are empty or ambiguous: %s' % track.name)
        names.add(key)
        if not (track.parent == -1 or 0 <= track.parent < i):
            raise ValueError('Animation parents must precede their children')
        if len(track.pivot) != 3 or len(track.rot) % 4 or len(track.pos) % 3:
            raise ValueError('The animation has incomplete bone keys')
        if any(n not in (0, 1, len(times)) for n in (track.rot_keys, track.pos_keys)):
            raise ValueError('Bone key counts do not match the animation times')
        if not all(math.isfinite(v) for v in (*track.pivot, *track.rot, *track.pos)):
            raise ValueError('The animation contains non-finite values')
        for at in range(0, len(track.rot), 4):
            if sum(v*v for v in track.rot[at:at+4]) < 1e-12:
                raise ValueError('The animation contains a zero quaternion')


def animationMatrices(animation, seconds):
    """Viewer world transforms and translation-only bind, in native CAS axes.

    Hold the endpoint instead of wrapping it to the first key when baking an
    Action. Playback looping is a caller choice; source root motion is retained.
    """
    end = animation.key_times[-1] if animation.key_times else 0.0
    if end and seconds >= end:
        local = []
        for track in animation.tracks:
            q = tuple(track.rot[-4:]) if track.rot_keys else (0, 0, 0, 1)
            off = track.pos[-3:] if track.pos_keys else (0, 0, 0)
            local.append({'rot': q, 'pos': tuple(p+o for p, o in zip(track.pivot, off))})
    else:
        local = casanim.sample(animation, max(0.0, seconds))
    pose, bind = [], []
    for track, sample in zip(animation.tracks, local):
        x, y, z, w = sample['rot']
        matrix = Quaternion((w, x, y, z)).normalized().to_matrix().to_4x4()
        matrix.translation = sample['pos']
        parent = track.parent
        pose.append(pose[parent] @ matrix if parent >= 0 else matrix)
        bind.append((bind[parent] if parent >= 0 else Vector((0, 0, 0))) + Vector(track.pivot))
    return pose, bind


def rigSignature(rig):
    state = [(b.name, b.parent.name if b.parent else '',
              [float(v) for row in b.matrix_local for v in row],
              b.inherit_scale, b.use_inherit_rotation, b.use_local_location)
             for b in rig.data.bones]
    return hashlib.sha256(json.dumps(state).encode()).hexdigest()


def buildAnimationAction(rig, animation, *, fps=24.0, start_frame=1.0, name=None):
    """Return (report, new Action), leaving the rig and its active Action alone.

    Bake on scene-frame times plus all source keys. Quaternion signs are made
    continuous and curves use linear interpolation. Exact source/end/frame
    samples match the viewer; subframes interpolate the baked channels.
    """
    if rig is None or rig.type != 'ARMATURE' or not rig.data.bones:
        raise ValueError('Select an armature with bones')
    _validate(animation)
    if not math.isfinite(fps) or not 0 < fps <= 1000 or not math.isfinite(start_frame):
        raise ValueError('Choose a finite positive frame rate and start frame')
    tracks = {_nameKey(t.name): i for i, t in enumerate(animation.tracks)}
    hub = next((i for i, t in enumerate(animation.tracks) if t.parent == 0), 0)
    mapping, missing = {}, []
    for bone in rig.data.bones:
        index = tracks.get(_nameKey(bone.get('med2_cas_node_name', bone.name)))
        if index is None:
            missing.append(bone.name)
            index = hub
        mapping[bone.name] = index
    if len(missing) == len(mapping):
        raise ValueError('The rig shares no bone names with this animation')
    end = animation.key_times[-1] if animation.key_times else 0.0
    if end * fps > 20000:
        raise ValueError('Animation exceeds 20,000 baked frames')
    if abs(start_frame) + end*fps > 1_000_000:
        raise ValueError('Animation lies outside the supported Blender frame range')
    # Key coordinates are float32. A source time such as float32(0.05)
    # and scene frame 1/20 must not create two keys at the same stored frame.
    by_frame = {}
    for seconds in [*(i/fps for i in range(int(math.floor(end*fps)) + 1)),
                    0.0, *map(float, animation.key_times), float(end)]:
        frame = struct.unpack('<f', struct.pack('<f', start_frame + seconds*fps))[0]
        by_frame[frame] = seconds
    frames = sorted(by_frame)
    times = [by_frame[frame] for frame in frames]
    if len(times) * len(mapping) * 10 > 5_000_000:
        raise ValueError('Animation exceeds five million channel keys')
    values = {bone.name: [] for bone in rig.data.bones}
    previous = {}
    for seconds in times:
        pose, bind = animationMatrices(animation, seconds)
        targets = {bone.name: CAS_TO_BLENDER @ pose[mapping[bone.name]] @
                   Matrix.Translation(-bind[mapping[bone.name]]) @ CAS_TO_BLENDER @ bone.matrix_local
                   for bone in rig.data.bones}
        for bone in rig.data.bones:
            kwargs = {'parent_matrix': targets[bone.parent.name],
                      'parent_matrix_local': bone.parent.matrix_local} if bone.parent else {}
            basis = bone.convert_local_to_pose(targets[bone.name], bone.matrix_local, invert=True, **kwargs)
            location, rotation, scale = basis.decompose()
            if bone.name in previous and rotation.dot(previous[bone.name]) < 0:
                rotation.negate()
            previous[bone.name] = rotation.copy()
            values[bone.name].append((*location, *rotation, *scale))
    result = bpy.data.actions.new(name or ('%s | %s' % (getattr(animation, 'med2_skeleton', 'Animation'), Path(animation.source).stem)))
    try:
        if hasattr(result, 'slots'):
            slot = result.slots.new('OBJECT', rig.name)
            bag = result.layers.new('Game animation').strips.new(type='KEYFRAME').channelbags.new(slot)
            new_curve = lambda path, index, group: bag.fcurves.new(path, index=index, group_name=group)
        else:
            new_curve = lambda path, index, group: result.fcurves.new(path, index=index, action_group=group)
        for bone in rig.pose.bones:
            for property_name, start, width in (('location', 0, 3), ('rotation_quaternion', 3, 4), ('scale', 7, 3)):
                for index in range(width):
                    curve = new_curve(bone.path_from_id(property_name), index, bone.name)
                    curve.keyframe_points.add(len(frames))
                    curve.keyframe_points.foreach_set('co', [v for frame, row in zip(frames, values[bone.name])
                                                           for v in (frame, row[start+index])])
                    for point in curve.keyframe_points:
                        point.interpolation = 'LINEAR'
                    curve.update()
        result['med2_animation'] = True
        result['med2_animation_source'] = str(animation.source)
        result['med2_animation_skeleton'] = getattr(animation, 'med2_skeleton', '')
        result['med2_animation_rig_signature'] = rigSignature(rig)
        result['med2_animation_fps'] = fps
        result['med2_animation_start'] = start_frame
        result['med2_animation_end'] = frames[-1]
        result['med2_animation_bones'] = json.dumps(list(mapping))
        result.use_fake_user = True
        report = [('WARNING', '%s -> %s (animation track missing)' % (bone, animation.tracks[hub].name)) for bone in missing]
        report.append(('INFO', 'Created %s: %d sampled frames, %d bones' % (result.name, len(frames), len(mapping))))
        return report, result
    except Exception:
        bpy.data.actions.remove(result)
        raise


def activateAnimationAction(rig, action):
    """Explicit activation; refuse changed rest rigs or overriding controllers."""
    if not action.get('med2_animation') or action.get('med2_animation_rig_signature') != rigSignature(rig):
        raise ValueError('The Action was built for a different rest rig; rebuild it')
    names = json.loads(action['med2_animation_bones'])
    if any(not c.mute and c.influence > 0 for name in names for c in rig.pose.bones[name].constraints):
        raise ValueError('Bone constraints override playback; detach the control rig before activating this Action')
    data = rig.animation_data
    if data and ((data.use_nla and any(not t.mute and t.strips for t in data.nla_tracks)) or
                 any(not d.mute and d.data_path.startswith('pose.bones[') for d in data.drivers)):
        raise ValueError('NLA tracks or drivers override playback; disable them before activating this Action')
    data = rig.animation_data_create()
    previous = (data.action, getattr(data, 'action_slot', None))
    modes = {name: rig.pose.bones[name].rotation_mode for name in names}
    try:
        data.action = action
        if hasattr(action, 'slots'):
            data.action_slot = action.slots[0]
        for name in names:
            rig.pose.bones[name].rotation_mode = 'QUATERNION'
    except Exception:
        data.action = previous[0]
        if previous[1] is not None:
            data.action_slot = previous[1]
        for name, mode in modes.items():
            rig.pose.bones[name].rotation_mode = mode
        raise
