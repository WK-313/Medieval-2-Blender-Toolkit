"""Launching an IWTE task file and watching for the file it produces.

IWTE is a GUI program driven from the command line with `--uh --st <task file>`.
It reports nothing back: no exit code worth reading, no progress, and it can
still be flushing its output well after the process has gone. So a conversion is
tracked by watching for the file it was asked to write, and is only called
finished once that file exists, is newer than whatever was there before, and has
stopped growing.

Both the unit export (GLB -> .mesh) and the strat export (GLB -> .cas) run
through here; the caller supplies the task file and the output it expects.
"""
import os
import math
import shutil
import subprocess
import time

# How long to keep watching the folder after the IWTE process has exited.
IWTE_OUTPUT_TIMEOUT = 300.0
# The output counts as written once it has stopped growing for this long.
IWTE_QUIET_SECONDS = 1.0
# How long a conversion may run before the toolkit asks whether to keep waiting.
# There is no upper bound on how long IWTE can legitimately take - a whole
# faction's meshes is minutes of work - so this is a prompt, never a kill: the
# answer defaults to carrying on. Each prompt doubles the next interval so a
# genuinely long job backs off instead of nagging.
IWTE_STALL_SECONDS = 180.0
# The longest a BLOCKING task run (the import side, which has no event loop to
# drive a prompt from) freezes Blender before it gives up waiting. IWTE is left
# running - whatever it has written by then is used, and anything still missing
# is reported - because killing it mid-conversion is how you get a half-written
# .glb that then has to be found and deleted by hand.
IWTE_TASK_TIMEOUT = 900.0
# How often a blocking wait prints that it is still going, so the system console
# the stall message points at actually has something in it.
IWTE_HEARTBEAT_SECONDS = 15.0

# Windows CREATE_NO_WINDOW: IWTE brings up its own window, the console behind it
# is just noise. Off Windows the flag does not exist and subprocess rejects any
# value but 0, so that is what it becomes.
NO_CONSOLE_WINDOW = 0x08000000 if os.name == 'nt' else 0

# The message every caller gives back when a Windows tool cannot be run here.
NO_WINE = ("%s is a Windows program and Wine was not found. Install Wine and make "
           "sure `wine` is on PATH")


def wineWrap(command):
    """A command for a Windows .exe, as it has to be run on this platform.

    IWTE and texconv are both Windows-only, so on Linux and macOS they go
    through Wine - which is how Medieval 2 itself is run there, so a modder on
    Linux already has it. Returns [] when there is no way to run the program,
    which lets callers report that instead of a FileNotFoundError coming out of
    subprocess."""
    if os.name == 'nt' or not command:
        return list(command)
    command = [str(part) for part in command]
    if not command[0].lower().endswith('.exe'):
        return command
    wine = shutil.which('wine')
    return [wine] + command if wine else []


def usesWine(program):
    """Whether running `program` here means going through Wine - which is what
    decides whether the paths handed to it have to be Windows paths."""
    return os.name != 'nt' and str(program).lower().endswith('.exe')


_wine_paths = {}


def winePath(path):
    """A path as a program running under Wine has to be given it.

    A POSIX path is not absolute to a Windows program: IWTE takes
    /home/you/m2tw/IWTE/iwte_tasks/task.txt for a relative path and looks for it
    under its own folder, which is where the doubled
    z:/home/you/m2tw/iwte/home/you/m2tw/iwte/iwte_tasks/task.txt comes from. The
    same applies to every path written INSIDE a task file, since IWTE resolves
    those the same way.

    `winepath -w` does the conversion properly, honouring whatever drives the
    prefix maps; when it cannot be run the fallback is Wine's default mapping of
    the filesystem root to Z:. On Windows the path is returned untouched, and so
    is one that already carries a drive letter. A trailing separator is kept -
    IWTE's directory fields are written with one on purpose."""
    if os.name == 'nt' or not path:
        return path
    path = str(path)
    if len(path) > 1 and path[1] == ':':
        return path
    cached = _wine_paths.get(path)
    if cached is not None:
        return cached
    trailing = path.endswith(('/', '\\'))
    source = path.rstrip('/\\') or '/'
    converted = ''
    command = ([shutil.which('winepath')] if shutil.which('winepath')
               else ([shutil.which('wine'), 'winepath'] if shutil.which('wine') else None))
    if command:
        try:
            result = subprocess.run(command + ['-w', source], capture_output=True,
                                    text=True, timeout=20)
            converted = result.stdout.strip()
        except (OSError, subprocess.SubprocessError):
            converted = ''
    if not converted:
        # Wine maps the filesystem root to Z: unless the prefix says otherwise
        absolute = source if source.startswith('/') else os.path.abspath(source)
        converted = 'Z:' + absolute.replace('/', '\\')
    if trailing and not converted.endswith('\\'):
        converted += '\\'
    _wine_paths[path] = converted
    return converted


def canRunWindowsExe():
    """Whether a Windows .exe can be launched at all here. Callers check this
    up front so they can report it in their own results popup rather than
    letting subprocess raise into the operator."""
    return os.name == 'nt' or shutil.which('wine') is not None


def findIWTEExe(iwte_dir):
    """The IWTE executable inside a folder, or None. The file name carries the
    version (IWTE_v26_05_A.exe), so it is matched by prefix."""
    try:
        names = os.listdir(iwte_dir)
    except OSError:
        return None
    return next(
        (os.path.join(iwte_dir, name) for name in names
         if name.lower().startswith("iwte") and name.lower().endswith(".exe")),
        None
    )


def startIWTETask(iwte_exe, iwte_dir, task_path, output_path):
    """Run a task file and return the job dict the watchers below expect."""
    command = wineWrap([iwte_exe, "--uh", "--st", winePath(task_path)])
    if not command:
        raise FileNotFoundError(NO_WINE % "IWTE")

    try:
        previous_mtime = os.path.getmtime(output_path)
    except OSError:
        previous_mtime = None

    process = subprocess.Popen(
        command,
        cwd=iwte_dir,
        creationflags=NO_CONSOLE_WINDOW
    )

    now = time.time()
    return {
        'process': process,
        'output_path': output_path,
        'output_name': os.path.basename(output_path),
        'previous_mtime': previous_mtime,
        'start': now,
        'stall_interval': IWTE_STALL_SECONDS,
        'stall_deadline': now + IWTE_STALL_SECONDS,
    }


def iwteProgress(elapsed):
    """IWTE gives no percentage feedback, so the bar eases toward full over
    time and jumps to done when the file lands on disk."""
    return 1.0 - math.exp(-elapsed / 10.0)


def iwteStalled(job):
    """Whether this job has run long enough that the user should be asked what
    to do with it. Nothing here decides to stop - the caller prompts, and the
    default answer is to carry on."""
    deadline = job.get('stall_deadline')
    return deadline is not None and time.time() >= deadline


def rearmStall(job):
    """Give the job another - longer - stretch before it asks again. Doubling
    means a conversion that is simply big is asked about once or twice rather
    than every three minutes for the rest of the afternoon."""
    interval = job.get('stall_interval', IWTE_STALL_SECONDS) * 2
    job['stall_interval'] = interval
    job['stall_deadline'] = time.time() + interval


def abortIWTEJob(job):
    """Stop the conversion at the user's request. The process is killed rather
    than asked to close: IWTE has no console to send a break to, and the window
    it puts up is waiting on the conversion, not on input."""
    job['aborted'] = True
    job['stall_deadline'] = None
    process = job.get('process')
    if process is not None and process.poll() is None:
        try:
            process.kill()
        except OSError:
            pass


def openSystemConsole():
    """Show Blender's system console, so the toolkit's own output is visible
    while a conversion runs. Only Windows builds have one to toggle; everywhere
    else Blender was started from a terminal that is already showing it."""
    import bpy
    if not hasattr(bpy.ops.wm, 'console_toggle'):
        return False
    try:
        bpy.ops.wm.console_toggle()
    except RuntimeError:
        return False
    return True


def hasSystemConsole():
    import bpy
    return hasattr(bpy.ops.wm, 'console_toggle')


def redrawView3D(context):
    for window in context.window_manager.windows:
        for area in window.screen.areas:
            if area.type == 'VIEW_3D':
                area.tag_redraw()


def iwteOutputReady(job):
    """True once the output exists, is newer than any pre-existing file, and
    has stopped changing (same size as last check and quiet for a moment)."""
    try:
        stat = os.stat(job['output_path'])
    except OSError:
        return False
    if job['previous_mtime'] is not None and stat.st_mtime <= job['previous_mtime']:
        return False
    if stat.st_size <= 0 or time.time() - stat.st_mtime < IWTE_QUIET_SECONDS:
        return False
    if stat.st_size != job.get('last_size'):
        job['last_size'] = stat.st_size
        return False
    return True


def finishIWTEJob(job, success):
    """Compose the (level, message) report for a finished conversion."""
    elapsed = time.time() - job['start']
    if success:
        size = os.stat(job['output_path']).st_size
        return ('INFO', "IWTE conversion finished: %s (%d KB) in %.1fs" % (job['output_name'], max(1, size // 1024), elapsed))
    if job.get('aborted'):
        return ('WARNING', "IWTE conversion aborted after %.0fs - %s was not written"
                           % (elapsed, job['output_name']))
    returncode = job['process'].returncode
    verb = "updated" if job['previous_mtime'] is not None else "created"
    return ('ERROR', "IWTE exited (code %s) but %s was not %s within %ds - check the task file and IWTE window" % (returncode, job['output_name'], verb, int(IWTE_OUTPUT_TIMEOUT)))


def waitForIWTEJob(job):
    """Blocking wait, for headless runs where there is no event loop to drive a
    modal operator's timer. Returns True when the output landed."""
    job['process'].wait()
    deadline = time.time() + IWTE_OUTPUT_TIMEOUT
    success = iwteOutputReady(job)
    while not success and time.time() < deadline:
        time.sleep(0.5)
        success = iwteOutputReady(job)
    return success


def waitForTaskProcess(process, label):
    """Block on a task-file run, printing a heartbeat and giving up eventually.

    This is the import side, where there is no modal operator and so no way to
    put a question on screen while the wait is happening - Blender's UI is held
    by the operator that started it. So the two things that CAN be done are done
    instead: the console gets a line every few seconds, which is what the stall
    message tells people to go and look at, and the wait is bounded so a hung
    IWTE cannot freeze Blender for the rest of the session.

    Returns True if IWTE finished on its own. On False it is still running - it
    is deliberately not killed, since a half-written .glb is worse than a slow
    one, and the caller reports which models did not appear."""
    start = time.time()
    next_beat = start + IWTE_HEARTBEAT_SECONDS
    while True:
        if process.poll() is not None:
            return True
        now = time.time()
        if now - start >= IWTE_TASK_TIMEOUT:
            print("Medieval 2 Toolkit: %s has been running for %.0fs - no longer waiting. "
                  "IWTE has been left running; re-run the import once it has finished."
                  % (label, now - start))
            return False
        if now >= next_beat:
            print("Medieval 2 Toolkit: %s still running (%.0fs)..." % (label, now - start))
            next_beat = now + IWTE_HEARTBEAT_SECONDS
        time.sleep(0.25)
