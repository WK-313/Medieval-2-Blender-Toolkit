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
    command = wineWrap([iwte_exe, "--uh", "--st", task_path])
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

    return {
        'process': process,
        'output_path': output_path,
        'output_name': os.path.basename(output_path),
        'previous_mtime': previous_mtime,
        'start': time.time(),
    }


def iwteProgress(elapsed):
    """IWTE gives no percentage feedback, so the bar eases toward full over
    time and jumps to done when the file lands on disk."""
    return 1.0 - math.exp(-elapsed / 10.0)


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
