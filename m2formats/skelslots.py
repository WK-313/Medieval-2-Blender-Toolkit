r"""The 687 slots named, and ``descr_skeleton.txt`` held against the packs (Phase 78).

A packed skeleton keeps its animations in 687 slots in the engine's fixed
order, and a slot carries no name, only its position. The names are
``descr_skeleton.txt``'s (``anim stand_a_idle <path>``), and the table that
joins the two, ``data/skeleton_slots.json``, was built by aligning the text
with the packs wherever the two agree: every skeleton on vanilla, ROCSS and
DaC whose text names exactly as many animations as its pack fills
(``dev/reference/skeleton_slots.py``, which says how).

**Every one of the 687 slots has a name** since 2026-09-26. The measurement
names 462 (455 before Reforged was installed again), every slot an installed
skeleton fills but one; a few of them only as a group whose names always share
a path (``die_to_back_right_2`` and ``die_to_back_left_2`` on 91 and 93). A list
of the engine's 687 names in order, shared by the user's friend
(``dev/reference/m2_slot_names.json``), agrees with every measured slot, so it
names the rest and says which slot of a group is which. :func:`measured` says
whether a slot's name was measured or taken from that list. A group still
shows as ``a / b`` if a table without the list is ever loaded.

**The packs are the truth.** Many mods appended to their packs, so the text is
often out of step with them, and the game plays the packs. :func:`report`
says how far out, for one mod: types the text has and the pack does not,
skeletons the pack has and the text does not, and per skeleton the slots
where the two disagree.

**And the modeldb held against the pack** (Phase 79): :func:`modeldb_findings`
lists every body or weapon skeleton a modeldb entry names that the mod's own
``skeletons.idx`` has not got, which Health reports. A weapon skeleton is a
warning, not a crash: it only shows when the mesh has weight on the weapon
bones (Makanyane).
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, List, Optional, Tuple


_TABLE_PATH = Path(__file__).resolve().parent / "data" / "skeleton_slots.json"
_TABLE: Optional[Tuple[Tuple[str, ...], ...]] = None
_BY_NAME: Dict[str, Tuple[int, ...]] = {}
_MEASURED: set = set()


def _load():
    global _TABLE
    if _TABLE is None:
        doc = json.loads(_TABLE_PATH.read_text(encoding="utf-8"))
        raw = doc["slots"]
        _MEASURED.update(doc.get("measured") or [i for i, v in enumerate(raw) if v])
        table = []
        for i, v in enumerate(raw):
            names = () if v is None else (v,) if isinstance(v, str) else tuple(v)
            table.append(names)
            for n in names:
                _BY_NAME[n] = _BY_NAME.get(n, ()) + (i,)
        _TABLE = tuple(table)
    return _TABLE


def names(slot: int) -> Tuple[str, ...]:
    """The slot's name, or its group's names; empty for a slot nothing names."""
    return _load()[slot]


def label(slot: int) -> str:
    """``stand_a_idle``, ``crew_right / crew_right_to_crew_stand`` for a group,
    or ``slot 312`` for one with no name."""
    n = names(slot)
    return " / ".join(n) if n else f"slot {slot}"


def slots_of(name: str) -> Tuple[int, ...]:
    """The slot an ``anim`` name fills, or every slot of its group; empty for a
    name the table does not know."""
    _load()
    return _BY_NAME.get(name.lower(), ())


def named() -> int:
    return sum(1 for n in _load() if n)


def measured(slot: int) -> bool:
    """Whether the slot's name was measured off the installed packs (True) or
    taken from the list of the engine's names (False)."""
    _load()
    return slot in _MEASURED


# families, so two hundred actions can be found (Phase 80)

#: The order the viewer lists them in; the first pattern a name matches wins.
FAMILIES = (
    ("stand", "Standing and idle", r"^(stand|idle|ready(?!_brace)|taunt|celebrate|selected|"
                                   r"er_stand|victory|pre_battle|general_signal)"),
    ("move", "Walking and running", r"^(walk|run(?!_attack)|shuffle|step|advance|combat_jog|"
                                    r"retreat|stealthy|hide|er_walk|er_run|jump)"),
    ("charge", "Charging", r"^charge"),
    ("attack", "Attacking", r"^(eager_attack|attack|run_attack)"),
    ("defend", "Defending", r"^eager_defend"),
    ("brace", "Braced formation", r"brace"),
    ("die", "Hit, knocked down and dying", r"^(die|knockback|knockdown|kill_mount|impact)"),
    ("crew", "Crews, carrying and siege", r"^(crew|carry|push|pull|raise_hand|siege|elephant)"),
    ("climb", "Climbing and swimming", r"^(climb|swim)"),
    ("agent", "Agents on the campaign map", r"^(build_settlement|ambush|no_mp|despoil|decimate|"
                                            r"insurrect|sabotage|assassinate|capture|spying|"
                                            r"conduct|refuse|druid)"),
    ("other", "Everything else", r""),
)
_FAMILY_RES = None


def family(name: str) -> str:
    """The family id of an ``anim`` name (``walk_to_run`` is ``move``)."""
    global _FAMILY_RES
    if _FAMILY_RES is None:
        import re
        _FAMILY_RES = [(fid, re.compile(rx)) for fid, _label, rx in FAMILIES]
    n = (name or "").lower()
    return next(fid for fid, rx in _FAMILY_RES if rx.search(n))
