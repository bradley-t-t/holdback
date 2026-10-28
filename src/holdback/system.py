"""What differs on Windows: where files live, whether a process is alive, background
processes, file locks, the console and the Claude CLI.

Everything else in Holdback is the same on every system. These functions decide at call
time, so the tests can stand in for Windows by patching os.name.
"""

from __future__ import annotations

import ntpath
import os
import platform
import shutil
import subprocess
import tempfile
from contextlib import contextmanager
from pathlib import Path

# Process creation flags from the Windows API, spelled out so this module also loads
# where the subprocess module doesn't define them.
DETACHED_PROCESS = 0x00000008
CREATE_NEW_PROCESS_GROUP = 0x00000200
CREATE_BREAKAWAY_FROM_JOB = 0x01000000

# install.ps1 records the folder it added to the user PATH here, so `holdback uninstall
# --all` takes out that entry and never one the person or another tool added.
REGISTRY_KEY = r"Software\Holdback"
PATH_VALUE = "PathAdded"


def windows() -> bool:
    return os.name == "nt"


def hostname() -> str:
    """The machine's short name, for the log."""
    return (platform.node() or "").split(".")[0]


def config_home() -> Path:
    """XDG_CONFIG_HOME when set, else %APPDATA% on Windows and ~/.config elsewhere."""
    if os.environ.get("XDG_CONFIG_HOME"):
        return Path(os.environ["XDG_CONFIG_HOME"])
    if windows() and os.environ.get("APPDATA"):
        return Path(os.environ["APPDATA"])
    return Path.home() / ".config"


def state_home() -> Path:
    """XDG_STATE_HOME when set, else %LOCALAPPDATA% on Windows and ~/.local/state
    elsewhere."""
    if os.environ.get("XDG_STATE_HOME"):
        return Path(os.environ["XDG_STATE_HOME"])
    if windows() and os.environ.get("LOCALAPPDATA"):
        return Path(os.environ["LOCALAPPDATA"])
    return Path.home() / ".local" / "state"


def temp_dirs() -> list:
    """The folders this system puts temporary files in."""
    out = [tempfile.gettempdir()]
    if windows():
        for var in ("TEMP", "TMP"):
            if os.environ.get(var):
                out.append(os.environ[var])
        local = os.environ.get("LOCALAPPDATA")
        if local:
            out.append(ntpath.join(local, "Temp"))
    else:
        out += ["/tmp", "/private/tmp", "/var/folders", "/private/var/folders", "/dev/shm"]
        if os.environ.get("TMPDIR"):
            out.append(os.environ["TMPDIR"])
    return [d.rstrip("/\\") or d for d in out if d]


def alive(pid) -> bool:
    """Whether that process is still running.

    os.kill(pid, 0) asks on POSIX. On Windows os.kill terminates the process whatever the
    signal, so there it opens a handle and asks the handle instead."""
    try:
        pid = int(pid)
    except (TypeError, ValueError):
        return False
    if windows():
        return _alive_windows(pid)
    try:
        os.kill(pid, 0)
        return True
    except PermissionError:
        return True                  # it runs, as someone else
    except OSError:
        return False


def _alive_windows(pid: int) -> bool:
    import ctypes
    PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
    STILL_ACTIVE = 259
    ERROR_ACCESS_DENIED = 5
    kernel32 = ctypes.windll.kernel32
    handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not handle:
        return kernel32.GetLastError() == ERROR_ACCESS_DENIED   # it runs, as someone else
    try:
        code = ctypes.c_ulong()
        if kernel32.GetExitCodeProcess(handle, ctypes.byref(code)):
            return code.value == STILL_ACTIVE
        return True
    finally:
        kernel32.CloseHandle(handle)


def start_detached(command, **popen_args) -> subprocess.Popen:
    """Start a process that outlives this one, with no terminal and no input or output.

    On Windows it also leaves this process's job, when the job allows that, since some
    hosts (an SSH session, for one) end every process in their job when they close."""
    quiet = dict(stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                 stderr=subprocess.DEVNULL, close_fds=True)
    if not windows():
        return subprocess.Popen(command, start_new_session=True, **quiet, **popen_args)
    flags = DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP
    try:
        return subprocess.Popen(command, creationflags=flags | CREATE_BREAKAWAY_FROM_JOB,
                                **quiet, **popen_args)
    except OSError:  # the job doesn't allow leaving it
        return subprocess.Popen(command, creationflags=flags, **quiet, **popen_args)


def run_after_exit(commands: list, delay: int = 3) -> None:
    """Run the commands one after another, in a detached cmd.exe, once this process has
    exited. Windows keeps a running program's files locked, so Holdback can't reinstall or
    remove itself while it is running. A command that fails stops the rest."""
    chain = " && ".join(subprocess.list2cmdline(c) for c in commands)
    # ping is the usual way to wait in cmd.exe: one ping a second, the first at once.
    line = "ping -n %d 127.0.0.1 >nul & %s" % (delay + 1, chain)
    start_detached('cmd.exe /d /s /c "%s"' % line)


class Locked(Exception):
    """Another process holds the lock."""


# Whichever of the two file locks this Python has. Asked for by name rather than by
# windows(), so a test standing in for Windows still locks with what is really here.
try:
    import fcntl as _fcntl
except ImportError:  # Windows
    _fcntl = None
try:
    import msvcrt as _msvcrt
except ImportError:  # everywhere else
    _msvcrt = None


@contextmanager
def exclusive_lock(path):
    """Hold path as a lock for the block, or raise Locked when someone else has it."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    f = open(path, "a+")
    try:
        try:
            if _fcntl is not None:
                _fcntl.flock(f.fileno(), _fcntl.LOCK_EX | _fcntl.LOCK_NB)
            else:
                _msvcrt.locking(f.fileno(), _msvcrt.LK_NBLCK, 1)
        except OSError:
            raise Locked(str(path)) from None
        try:
            yield f
        finally:
            try:
                if _fcntl is not None:
                    _fcntl.flock(f.fileno(), _fcntl.LOCK_UN)
                else:
                    f.seek(0)
                    _msvcrt.locking(f.fileno(), _msvcrt.LK_UNLCK, 1)
            except OSError:
                pass
    finally:
        f.close()


def python_command() -> str:
    """The name that starts Python here. On Windows, python3 is often only the Store's
    placeholder under WindowsApps, which runs nothing."""
    for name in ("python3", "python", "py"):
        found = shutil.which(name)
        if found and not (windows() and "windowsapps" in found.lower()):
            return name
    return "python3"


# Where the Claude Code CLI usually lives, for a hook that runs with a short PATH.
CLAUDE_DIRS = ("~/.local/bin", "/opt/homebrew/bin", "/usr/local/bin", "/usr/bin",
               "~/.claude/local", "~/AppData/Roaming/npm", "~/AppData/Local/Microsoft/WinGet/Links",
               "~/scoop/shims")


def claude_bin() -> str:
    """The Claude Code CLI, which runs the judge: whatever is on PATH, else the usual
    places. On Windows that is usually claude.cmd."""
    names = ("claude.cmd", "claude.exe", "claude") if windows() else ("claude",)
    for name in names:
        found = shutil.which(name)
        if found:
            return found
    for d in CLAUDE_DIRS:
        for name in names:
            p = Path(d).expanduser() / name
            if p.is_file():
                return str(p)
    return "claude"


def program_command(program: str, args: list) -> list:
    """The command that runs program with args. On Windows a .cmd or .bat is a script for
    the command processor, not a program CreateProcess can start on its own."""
    if windows() and program.lower().endswith((".cmd", ".bat")):
        return [os.environ.get("COMSPEC") or "cmd.exe", "/d", "/s", "/c", program] + list(args)
    return [program] + list(args)


def same_path(a: str, b: str) -> bool:
    """Whether two paths name the same place. Windows compares without case and over both
    separators."""
    def norm(p: str) -> str:
        p = (p or "").strip().rstrip("\\/")
        return ntpath.normcase(ntpath.normpath(p)) if windows() else os.path.normpath(p)
    return bool(a) and bool(b) and norm(a) == norm(b)


def remove_user_path_entry() -> str:
    """Take the folder install.ps1 added out of the Windows user PATH. Returns the
    folder, or "" when install.ps1 didn't add one or it's already gone."""
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, REGISTRY_KEY) as k:
            folder = winreg.QueryValueEx(k, PATH_VALUE)[0]
    except OSError:
        return ""
    removed = ""
    access = winreg.KEY_READ | winreg.KEY_WRITE
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment", 0, access) as k:
        try:
            value, kind = winreg.QueryValueEx(k, "Path")
        except OSError:
            value, kind = "", winreg.REG_EXPAND_SZ
        parts = [p for p in value.split(";") if p]
        kept = [p for p in parts if not same_path(ntpath.expandvars(p), folder)]
        if kept != parts:
            winreg.SetValueEx(k, "Path", 0, kind, ";".join(kept))
            removed = folder
    try:
        winreg.DeleteKey(winreg.HKEY_CURRENT_USER, REGISTRY_KEY)
    except OSError:
        pass
    if removed:
        _announce_environment_change()
    return removed


def _announce_environment_change() -> None:
    """Tell open programs the user environment changed, as setx does, so new terminals
    started from Explorer see the new PATH."""
    import ctypes
    from ctypes import wintypes
    result = wintypes.DWORD()
    ctypes.windll.user32.SendMessageTimeoutW(0xFFFF, 0x001A, 0, "Environment", 0x0002, 5000,
                                             ctypes.byref(result))


_vt_mode = None


def ansi_colors() -> bool:
    """Whether the console shows ANSI colors. Windows 10 and later do once the console's
    escape-sequence mode is on, which this turns on the first time it's asked."""
    global _vt_mode
    if not windows():
        return True
    if _vt_mode is None:
        _vt_mode = False
        try:
            import ctypes
            kernel32 = ctypes.windll.kernel32
            handle = kernel32.GetStdHandle(-11)  # standard output
            mode = ctypes.c_uint32()
            if kernel32.GetConsoleMode(handle, ctypes.byref(mode)):
                # ENABLE_VIRTUAL_TERMINAL_PROCESSING
                _vt_mode = bool(kernel32.SetConsoleMode(handle, mode.value | 0x0004))
        except Exception:  # noqa: BLE001
            pass
    return _vt_mode
