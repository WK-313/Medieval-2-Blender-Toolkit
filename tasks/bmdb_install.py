"""Write a BMDB entry and its files straight into a mod.

Mirrors the way the Unit Transfer tool handles the same job: a plan is built
first and reports everything that would happen - the entry name already being
taken, an identical entry already being there, destination files that differ
byte for byte, other models that share those files - and nothing touches the mod
until the caller applies a plan it has seen.

Deliberately free of `bpy` so the planning rules can be tested headlessly.
"""

import filecmp
import os
import shutil
import time

from . import modeldb

# Entry-name conflict modes, matching the Unit Transfer tool's `on_conflict`.
CONFLICT_SKIP = 'skip'
CONFLICT_RENAME = 'rename'
CONFLICT_OVERWRITE = 'overwrite'

# What to do with a destination file that already exists with different content.
ASSET_KEEP = 'use_existing'
ASSET_OVERWRITE = 'overwrite'

# File states found while planning.
STATE_NEW = 'new'              # not in the mod yet
STATE_IDENTICAL = 'identical'  # already there, byte for byte the same
STATE_DIFFERS = 'differs'      # already there with different content
STATE_IN_PLACE = 'in_place'    # source and destination are the same file
STATE_ONLY_DEST = 'only_dest'  # not exported this time, but already in the mod
STATE_MISSING = 'missing'      # nowhere to be found


class FileAction:
    def __init__(self, rel, src, dst, state, kind):
        self.rel = rel            # path relative to the mod's data folder
        self.src = src            # absolute path in the export folder
        self.dst = dst            # absolute path in the mod
        self.state = state
        self.kind = kind          # 'mesh' | 'texture'
        self.shared = []          # other entries referencing this exact path
        self.applied = ''         # filled in by applyInstall

    def willCopy(self, asset_conflict):
        if self.state in (STATE_NEW,):
            return True
        if self.state == STATE_DIFFERS:
            return asset_conflict == ASSET_OVERWRITE
        return False


class InstallPlan:
    def __init__(self, mod_folder, out_dir, relative):
        self.mod_folder = mod_folder
        self.out_dir = out_dir
        self.relative = relative
        self.entry_name = ''
        self.final_name = ''
        self.entry_text = ''
        self.entry_action = ''     # add | overwrite | rename | identical | skip
        self.existing = None       # the modeldb entry being replaced, if any
        self.files = []
        self.on_conflict = CONFLICT_RENAME
        self.asset_conflict = ASSET_KEEP
        self.backup = True
        self.backup_path = ''
        self.errors = []
        self.warnings = []
        self.notes = []

    def blocked(self):
        return bool(self.errors)

    def results(self):
        """(level, message) pairs in the shape the panels' popup helper wants."""
        return ([('ERROR', message) for message in self.errors]
                + [('WARNING', message) for message in self.warnings]
                + [('INFO', message) for message in self.notes])


def modelUsers(unit_dictionary):
    """model name -> the unit ids that use it, from the read-in unit dictionary.

    Lets the plan name the units that would be affected before an existing entry
    gets overwritten."""
    users = {}
    for unit, info in (unit_dictionary or {}).items():
        for key in ('Model', 'Officers'):
            for model in info.get(key) or []:
                users.setdefault(str(model).lower(), [])
                if unit not in users[str(model).lower()]:
                    users[str(model).lower()].append(unit)
    return users


def _pathUsers(db, skip_name):
    """data-relative file path -> the entries referencing it, ignoring one."""
    users = {}
    for entry in db.entries:
        if entry.name == skip_name:
            continue
        for path in entry.mesh_files() + entry.texture_files():
            users.setdefault(path.lower().replace("\\", "/"), []).append(entry.name)
    return users


def _sourceFor(out_dir, relative, rel):
    """Where the export wrote the file that `rel` names in the mod.

    The export folder mirrors the entry's own layout - `<name>.mesh` at the top
    and the textures under `textures/` - so the part of `rel` below the entry
    path is also its path inside the export folder."""
    rel_norm = rel.replace("\\", "/").lower()
    prefix = relative.replace("\\", "/").lower().rstrip("/") + "/"
    if not rel_norm.startswith(prefix):
        return None
    return os.path.join(out_dir, *rel[len(prefix):].replace("\\", "/").split("/"))


def _sameFile(a, b):
    try:
        return os.path.samefile(a, b)
    except OSError:
        return False


def planInstall(mod_folder, out_dir, entry_text, relative, on_conflict=CONFLICT_RENAME,
                new_name='', asset_conflict=ASSET_KEEP, backup=True, unit_dictionary=None):
    """Work out exactly what installing `entry_text` into `mod_folder` would do."""
    plan = InstallPlan(mod_folder, out_dir, relative)
    plan.entry_text = entry_text.strip("\n")
    plan.on_conflict = on_conflict
    plan.asset_conflict = asset_conflict
    plan.backup = backup

    if not relative:
        plan.errors.append("No mesh path set - the entry has nowhere to point")
        return plan
    if not os.path.isdir(out_dir):
        plan.errors.append("Export folder not found: %s - export the unit first" % out_dir)
        return plan

    db, error = modeldb.loadModelDb(mod_folder)
    if db is None:
        plan.errors.append(error)
        return plan

    try:
        new_entry = modeldb.parse_entry_text(plan.entry_text)
    except ValueError as parse_error:
        plan.errors.append(str(parse_error))
        return plan

    plan.entry_name = new_entry.name
    plan.final_name = new_entry.name
    _planEntry(plan, db, new_entry, new_name, unit_dictionary)
    if plan.entry_action == CONFLICT_SKIP:
        return plan
    _planFiles(plan, db, new_entry)
    return plan


def _planEntry(plan, db, new_entry, new_name, unit_dictionary):
    existing = db.get(new_entry.name)
    if existing is None:
        plan.entry_action = 'add'
        plan.notes.append("Entry '%s' is new - it will be appended and the header count bumped"
                          % plan.final_name)
        return

    plan.existing = existing
    if existing.content_equals(new_entry):
        plan.entry_action = 'identical'
        plan.notes.append("Entry '%s' already exists with identical content - it is left alone"
                          % existing.name)
        return

    users = modelUsers(unit_dictionary).get(existing.name, [])
    used_by = (" - used by %d unit(s): %s" % (len(users), ", ".join(users[:6])
                                              + (" ..." if len(users) > 6 else ""))) if users else ""

    if plan.on_conflict == CONFLICT_SKIP:
        plan.entry_action = CONFLICT_SKIP
        plan.warnings.append("Entry '%s' already exists with DIFFERENT content%s. Nothing was "
                             "installed - pick Rename or Overwrite to continue"
                             % (existing.name, used_by))
        return

    if plan.on_conflict == CONFLICT_RENAME:
        taken = set(db.by_name())
        wanted = (new_name or "").strip().lower()
        if wanted and wanted in taken:
            plan.errors.append("Rename target '%s' is also taken in battle_models.modeldb" % wanted)
            return
        plan.final_name = wanted or modeldb.uniqueName(new_entry.name, taken)
        plan.entry_action = CONFLICT_RENAME
        plan.entry_text = modeldb.rename_entry_raw(plan.entry_text, plan.final_name)
        plan.warnings.append("Entry '%s' already exists with different content%s - the new entry "
                             "is added as '%s' instead" % (existing.name, used_by, plan.final_name))
        plan.notes.append("Point the EDU's soldier/officer line at '%s', not '%s'"
                          % (plan.final_name, existing.name))
        return

    plan.entry_action = CONFLICT_OVERWRITE
    plan.warnings.append("Entry '%s' already exists and will be REPLACED%s"
                         % (existing.name, used_by))
    _warnOverwriteLoss(plan, existing, new_entry)


def _warnOverwriteLoss(plan, existing, new_entry):
    """Say what the replacement drops, since the generated entry is rebuilt from
    the export panel's fields and cannot know about anything richer."""
    if len(existing.lods) > len(new_entry.lods):
        plan.warnings.append("The existing entry has %d LOD mesh(es), the new one has %d - "
                             "the extra LODs are lost" % (len(existing.lods), len(new_entry.lods)))
    lost = [f for f in existing.factions() if f not in new_entry.factions()]
    if lost:
        plan.warnings.append("Skins lost for %d faction(s): %s - tick them under Ownership to keep them"
                             % (len(lost), ", ".join(lost[:8]) + (" ..." if len(lost) > 8 else "")))
    if existing.footer() and not new_entry.animations:
        plan.warnings.append("The new entry has no animation block - copy the sprite and footer "
                             "from a unit first, or the model has no skeleton in game")
    if existing.skeletons() and new_entry.skeletons() and \
            set(existing.skeletons()) != set(new_entry.skeletons()):
        plan.warnings.append("Skeletons change from %s to %s"
                             % (", ".join(sorted(set(existing.skeletons()))),
                                ", ".join(sorted(set(new_entry.skeletons())))))


def _planFiles(plan, db, new_entry):
    """Byte-compare every file the entry names against the mod's copy."""
    wanted = ([(rel, 'mesh') for rel in new_entry.mesh_files()]
              + [(rel, 'texture') for rel in new_entry.texture_files()])
    seen = set()
    for rel, kind in wanted:
        rel = rel.replace("\\", "/")
        if rel.lower() in seen:
            continue
        seen.add(rel.lower())
        if rel.lower().endswith('.spr'):
            plan.notes.append("Sprite '%s' is not copied - sprites are shared and stay where they are"
                              % rel)
            continue
        src = _sourceFor(plan.out_dir, plan.relative, rel)
        dst = os.path.join(plan.mod_folder, *rel.split("/"))
        if src is None:
            plan.notes.append("'%s' sits outside the entry path and is not copied" % rel)
            continue
        src_exists = os.path.isfile(src)
        dst_exists = os.path.isfile(dst)
        if not src_exists:
            state = STATE_ONLY_DEST if dst_exists else STATE_MISSING
        elif dst_exists and _sameFile(src, dst):
            state = STATE_IN_PLACE
        elif dst_exists:
            state = STATE_IDENTICAL if _identical(src, dst) else STATE_DIFFERS
        else:
            state = STATE_NEW
        plan.files.append(FileAction(rel, src, dst, state, kind))

    missing = [f for f in plan.files if f.state == STATE_MISSING]
    for action in missing:
        if action.kind == 'mesh':
            plan.errors.append("Mesh '%s' not found in the export folder or the mod - run "
                               "Export to Mesh (IWTE) first" % os.path.basename(action.rel))
        else:
            plan.errors.append("Texture '%s' not found in the export folder or the mod - the "
                               "unit would be untextured" % os.path.basename(action.rel))

    only_dest = [f for f in plan.files if f.state == STATE_ONLY_DEST]
    if only_dest:
        plan.notes.append("%d file(s) were not re-exported but are already in the mod: %s"
                          % (len(only_dest), ", ".join(os.path.basename(f.rel) for f in only_dest[:6])))

    differing = [f for f in plan.files if f.state == STATE_DIFFERS]
    if differing:
        users = _pathUsers(db, plan.final_name)
        for action in differing:
            action.shared = users.get(action.rel.lower(), [])
        if plan.asset_conflict == ASSET_OVERWRITE:
            plan.warnings.append("%d file(s) in the mod will be OVERWRITTEN: %s"
                                 % (len(differing), ", ".join(os.path.basename(f.rel) for f in differing[:6])))
        else:
            plan.warnings.append("%d file(s) already exist in the mod with DIFFERENT content and "
                                 "are kept as they are: %s - the unit uses the mod's versions. "
                                 "Switch to Overwrite, or rename the textures, if that is wrong"
                                 % (len(differing), ", ".join(os.path.basename(f.rel) for f in differing[:6])))
        shared = [f for f in differing if f.shared]
        for action in shared:
            verb = "Overwriting" if plan.asset_conflict == ASSET_OVERWRITE else "Keeping"
            tail = ("also re-skins %d other model(s): %s" if plan.asset_conflict == ASSET_OVERWRITE
                    else "means this unit shares the skin of %d other model(s): %s")
            plan.warnings.append("%s '%s' %s" % (verb, os.path.basename(action.rel),
                                                 tail % (len(action.shared), ", ".join(action.shared[:5])
                                                         + (" ..." if len(action.shared) > 5 else ""))))

    identical = [f for f in plan.files if f.state in (STATE_IDENTICAL, STATE_IN_PLACE)]
    if identical:
        plan.notes.append("%d file(s) are already in place unchanged and are not recopied"
                          % len(identical))


def _identical(src, dst):
    try:
        if os.path.getsize(src) != os.path.getsize(dst):
            return False
        return filecmp.cmp(src, dst, shallow=False)
    except OSError:
        return False


def _writeModeldb(path, text):
    """Write the rebuilt modeldb through a temp file, so a failure part way
    through cannot leave the mod with a half written battle_models.modeldb.
    Returns an error string, or '' on success."""
    temp = path + ".tmp"
    try:
        with open(temp, "w", encoding=modeldb.ENCODING, newline="") as modeldb_output:
            modeldb_output.write(text)
        os.replace(temp, path)
    except OSError as error:
        try:
            os.remove(temp)
        except OSError:
            pass
        return "Could not write battle_models.modeldb: %s" % error
    return ""


def applyInstall(plan):
    """Carry out a plan. Returns (level, message) pairs describing every change."""
    results = []
    if plan.blocked():
        return [('ERROR', message) for message in plan.errors]
    if plan.entry_action == CONFLICT_SKIP:
        return [('WARNING', message) for message in plan.warnings]

    db, error = modeldb.loadModelDb(plan.mod_folder)
    if db is None:
        return [('ERROR', error)]
    # the entries below are edited in place, so the cached parse has to go now
    # rather than after the write - a failed write must not leave the cache
    # describing a file that was never saved
    modeldb.invalidate(plan.mod_folder)

    path = modeldb.modeldbPath(plan.mod_folder)
    if plan.entry_action != 'identical':
        if plan.backup:
            plan.backup_path = "%s.%s.bak" % (path, time.strftime("%Y%m%d_%H%M%S"))
            try:
                shutil.copy2(path, plan.backup_path)
                results.append(('INFO', "Backed up battle_models.modeldb -> %s"
                                % os.path.basename(plan.backup_path)))
            except OSError as backup_error:
                return [('ERROR', "Could not back up battle_models.modeldb: %s" % backup_error)]

        try:
            entry = modeldb.parse_entry_text(plan.entry_text)
        except ValueError as parse_error:
            return [('ERROR', str(parse_error))]

        index = db.index_of(plan.final_name) if plan.entry_action == CONFLICT_OVERWRITE else -1
        if index >= 0:
            # keep whatever whitespace separated the old entry from the one
            # before it, so only this entry's bytes change
            old_raw = db.entries[index].raw
            entry.raw = old_raw[:len(old_raw) - len(old_raw.lstrip())] + plan.entry_text
            db.entries[index] = entry
            results.append(('INFO', "Replaced entry '%s' in battle_models.modeldb" % plan.final_name))
        else:
            # entries in the file carry their own leading newline; the file's
            # trailing bytes stay after whatever ends up last
            entry.raw = "\n" + plan.entry_text
            db.entries.append(entry)
            results.append(('INFO', "Added entry '%s' to battle_models.modeldb (%d models now)"
                            % (plan.final_name, len(db.entries))))
        error = _writeModeldb(path, db.to_text())
        if error:
            return results + [('ERROR', error)]

    for action in plan.files:
        if not action.willCopy(plan.asset_conflict):
            action.applied = 'skipped'
            continue
        try:
            os.makedirs(os.path.dirname(action.dst), exist_ok=True)
            shutil.copy2(action.src, action.dst)
        except OSError as copy_error:
            action.applied = 'failed'
            results.append(('ERROR', "Could not copy %s: %s" % (action.rel, copy_error)))
            continue
        action.applied = 'overwritten' if action.state == STATE_DIFFERS else 'copied'
        results.append(('INFO', "%s %s -> %s"
                        % (action.applied.capitalize(), os.path.basename(action.rel), action.rel)))

    kept = [f for f in plan.files if f.state == STATE_DIFFERS and f.applied == 'skipped']
    for action in kept:
        results.append(('WARNING', "Kept the mod's own %s (differs from the exported one)"
                        % os.path.basename(action.rel)))

    results.extend(('WARNING', message) for message in plan.warnings)
    results.extend(('INFO', message) for message in plan.notes)
    return results
