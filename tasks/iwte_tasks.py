"""The IWTE task files bundled with the addon.

One sample task file per QOL skeleton, in the addon's iwte_tasks folder. They
differ in the bone order and case IWTE writes into the .mesh and in the default
.cas animation, so a rig converts correctly only with the file for the skeleton
it is actually rigged to - which is why a rig parented through the QOL panel
gets its file assigned automatically.

The three lines the conversion rewrites anyway (input GLB, output folder,
output mesh name) are placeholders in the bundled copies.
"""
import os
from pathlib import Path

from .armature_tools import skeletonNames, skeletonOf

addon_folder = Path(__file__).parent.parent

TASK_PREFIX = 'iwte_extract_to_mesh_'
TASK_SUFFIX = '_task'


def sampleTasksFolder():
    return addon_folder/'iwte_tasks'

def sampleTaskFiles():
    folder = sampleTasksFolder()
    if not folder.is_dir():
        return []
    return sorted(folder.glob('*.txt'), key=lambda path: path.stem.lower())

def sampleTaskSkeleton(file_name):
    """The skeleton a sample file belongs to, from its name:
    iwte_extract_to_mesh_sword_task.txt -> 'sword'."""
    stem = Path(file_name).stem.lower()
    if stem.startswith(TASK_PREFIX):
        stem = stem[len(TASK_PREFIX):]
    if stem.endswith(TASK_SUFFIX):
        stem = stem[:-len(TASK_SUFFIX)]
    return stem

def sampleTaskLabel(file_name):
    """Menu label for a sample file: the skeleton's own spelling when it is one
    of the armatures folder's skeletons, else the name out of the file."""
    key = sampleTaskSkeleton(file_name)
    for name in skeletonNames():
        if name.lower() == key:
            return name
    return key.replace('_', ' ').title() or Path(file_name).stem

def sampleTaskForSkeleton(skeleton):
    """Full path of the sample task file for a skeleton, '' when there is none."""
    if not skeleton:
        return ''
    for path in sampleTaskFiles():
        if sampleTaskSkeleton(path.name) == skeleton.lower():
            return str(path)
    return ''

def clean(path):
    return os.path.normpath(path.strip('"').strip("'")) if path else ''

def isSampleTask(path):
    """True when a task template path points into the bundled samples folder."""
    if not path:
        return False
    folder = os.path.normcase(os.path.normpath(str(sampleTasksFolder())))
    parent = os.path.normcase(os.path.normpath(os.path.dirname(path.strip('"').strip("'"))))
    return parent == folder

def isMovedSample(path):
    """True for a task file that is gone from disk but carries the name of a
    bundled sample - a sample assigned under an install that has since moved."""
    name = os.path.basename(clean(path))
    if not name or os.path.isfile(clean(path)):
        return False
    return (sampleTasksFolder()/name).is_file()

def autoSampleTask(armature):
    """(sample task path, skeleton name) for the skeleton a rig is rigged to.
    Both are '' when the rig is not on one of the QOL skeletons."""
    skeleton = skeletonOf(armature)
    if not skeleton:
        return '', ''
    return sampleTaskForSkeleton(skeleton), skeleton

def applySkeletonTask(armature):
    """Point a rig at the sample task file for the skeleton it is rigged to.

    Only fills a blank template or replaces another bundled sample - a task
    file the user picked themselves is never overwritten. Returns the skeleton
    name when the template changed, else '' (already on it, or no match).
    """
    export_data = getattr(armature, 'med2_toolkit_unit_export', None)
    if export_data is None:
        return ''
    current = export_data.iwte_task_template
    if current and not isSampleTask(current) and not isMovedSample(current):
        return ''
    path, skeleton = autoSampleTask(armature)
    if not path or not os.path.isfile(path):
        return ''
    if os.path.normcase(clean(current)) == os.path.normcase(path):
        return ''
    export_data.iwte_task_template = path
    return skeleton
