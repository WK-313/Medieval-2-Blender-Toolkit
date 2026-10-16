"""Animation catalogue and persistent, validated Blender Action cache."""
import hashlib
import json
from pathlib import Path

import bpy

from ..m2formats import animpack, casanim, skelslots
from . import animation_engine as engine
from .pose_library import actionFCurves


def skeletonNames(root):
    names = {}
    for folder in reversed(engine._roots(root)):
        names.update({key: value.name for key, value in casanim.skeleton_types(folder).items()})
    packs, _ = animpack.packs_for(root)
    if packs:
        names.update({name.casefold(): name for name in packs.skeleton_names()})
    return sorted(names.values(), key=str.casefold)


def actionRows(root, skeleton):
    """Filled packed slots are authoritative; descriptors supply absent sets.

    Decode with the playback resolver so overrides, scale selection, counts and
    duration agree with the Action that will actually play. Broken rows stay
    visible with their error, rather than silently playing another source.
    """
    packs, _ = animpack.packs_for(root)
    packed = packs.skeleton(skeleton) if packs else None
    if packed:
        choices = [(skelslots.label(i), slot.path, i) for i, slot in packed.filled()]
    else:
        descriptor = next((types[skeleton.casefold()] for folder in engine._roots(root)
                           if (types := casanim.skeleton_types(folder)).get(skeleton.casefold())), None)
        if descriptor is None:
            raise ValueError('Skeleton not found: %s' % skeleton)
        choices = list(dict.fromkeys((name, path, -1) for name, path in descriptor.anims))
    rows = []
    order = {key: i for i, (key, _, _) in enumerate(skelslots.FAMILIES)}
    for name, path, slot in choices:
        row = dict(name=name, path=path, slot=slot, family=skelslots.family(name),
                   frames=0, duration=0.0, error='', source_kind='')
        try:
            animation = engine.loadAnimation(root, skeleton, **({'slot': slot} if slot >= 0 else {'path': path}))
            row.update(frames=len(animation.key_times),
                       duration=float(animation.key_times[-1]) if animation.key_times else 0.0,
                       source_kind=animation.med2_source_kind)
        except (OSError, ValueError, engine.casanim.AnimError) as error:
            row['error'] = str(error)
        rows.append(row)
    return sorted(rows, key=lambda row: (order[row['family']], row['name'].casefold(), row['slot']))


def curveDigest(action):
    """Detect pose-library clearing or user edits before reusing a cached Action."""
    digest = hashlib.sha256()
    for curve in actionFCurves(action):
        digest.update(repr((curve.data_path, curve.array_index, curve.mute,
                            [(tuple(p.co), p.interpolation, tuple(p.handle_left), tuple(p.handle_right))
                             for p in curve.keyframe_points],
                            [m.type for m in curve.modifiers])).encode())
    return digest.hexdigest()


def cachedAction(rig, root, skeleton, row, fps):
    animation = engine.loadAnimation(root, skeleton,
                                     **({'slot': row.slot} if row.slot >= 0 else {'path': row.path}))
    digest = hashlib.sha256()
    digest.update(repr((str(Path(root).resolve()), skeleton.casefold(), row.path, row.slot,
                       fps, animation.length, engine.rigSignature(rig),
                       [(b.name, b.get('med2_cas_node_name', b.name)) for b in rig.data.bones])).encode())
    digest.update(animation.key_times.tobytes())
    for track in animation.tracks:
        digest.update(repr((track.name, track.parent, track.pivot)).encode())
        digest.update(track.rot.tobytes())
        digest.update(track.pos.tobytes())
    key = digest.hexdigest()
    for action in bpy.data.actions:
        if (action.get('med2_animation_cache') == key and action.get('med2_animation')
                and not any(curve.modifiers for curve in actionFCurves(action))
                and action.get('med2_animation_curves') == curveDigest(action)):
            return [('INFO', 'Reused %s' % action.name)], action, False
    reports, action = engine.buildAnimationAction(rig, animation, fps=fps,
                                                 name='%s | %s' % (skeleton, row.name))
    action['med2_animation_cache'] = key
    action['med2_animation_curves'] = curveDigest(action)
    return reports, action, True


def suggestedSkeleton(rig):
    if rig is None:
        return ''
    try:
        return json.loads(rig.get('med2_strat_import_metadata', '{}')).get('skeleton', '')
    except (ValueError, TypeError, AttributeError):
        return ''
