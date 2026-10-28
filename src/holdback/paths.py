"""Where writing changes nothing of the person's, and working out which file a command
means.

The scratchpad, the system's temporary folders, Claude's own memory and plans, and anything
`holdback setup --allow-paths` was given. Everything else is the person's.
"""

from __future__ import annotations

import fnmatch
import ntpath
import os
import posixpath
import re
from pathlib import Path

from . import config, system

# Writing to one of these changes nothing, wherever it is.
SINKS = ("/dev/null", "/dev/stdout", "/dev/stderr", "/dev/tty", "/dev/fd/", "/dev/zero")
# What Windows calls them. These are whole names, not prefixes: config.json is a file.
WINDOWS_SINKS = {"nul", "con", "conout$", "conin$"}

# Variables the shell command being read has set so far.
SHELL_VARS = {}
VAR = re.compile(r"\$\{([A-Za-z_]\w*)\}|\$([A-Za-z_]\w*)")
# A Git Bash path for a Windows drive: /c/Users/... is C:\Users\...
GIT_BASH_DRIVE = re.compile(r"^/([A-Za-z])/")


def scratch_dirs() -> list:
    """Where writing changes nothing of the person's: temporary files (the session's
    scratchpad, a Tether draft), Claude's own memory and plans, and any paths setup was
    given."""
    home = str(Path.home())
    dirs = list(system.temp_dirs())
    dirs += [os.path.join(home, ".claude", "plans"),
             os.path.join(home, ".claude", "projects", "*", "memory")]
    dirs += [os.path.expanduser(p).rstrip("/\\") for p in config.settings().allow_paths]
    out = []
    for d in dirs:
        if d and d not in out:
            out.append(d)
    return out


def variables(text: str) -> str:
    """text with $NAME and ${NAME} filled in where the command set them or the environment
    has them; any other $ is left as it is."""
    def value(m):
        name = m.group(1) or m.group(2)
        if name in SHELL_VARS:
            return SHELL_VARS[name]
        if name == "HOME":
            return str(Path.home())
        if name == "TMPDIR":
            return (os.environ.get("TMPDIR") or system.temp_dirs()[0]).rstrip("/\\")
        return os.environ.get(name, m.group(0))
    return VAR.sub(value, text)


def _mod():
    """How this system spells paths. Named here rather than taken from os.path so the tests
    can stand in for Windows."""
    return ntpath if system.windows() else posixpath


def expand(path: str, cwd: str = ""):
    """An absolute path for path, or None when it can't be told (a variable nothing set, a
    relative path with no known folder)."""
    p = (path or "").strip()
    if not p:
        return None
    p = os.path.expanduser(variables(p))
    if "$" in p or "`" in p:
        return None
    mod = _mod()
    if system.windows():
        m = GIT_BASH_DRIVE.match(p)
        if m:                        # Git Bash spells C:\Users as /c/Users
            p = "%s:\\%s" % (m.group(1).upper(), p[3:].replace("/", "\\"))
    if not mod.isabs(p):
        if not cwd or not mod.isabs(cwd):
            return None
        p = mod.join(cwd, p)
    return mod.normpath(p)


def _norm(p: str) -> str:
    """A path as it compares on this system: Windows ignores case and both separators."""
    return ntpath.normcase(ntpath.normpath(p)) if system.windows() else p


def under(path: str, folder: str) -> bool:
    """Whether path is folder or inside it."""
    p, d = _norm(path), _norm(folder.rstrip("/\\"))
    if not d:
        return False
    return p == d or p.startswith(d + _mod().sep)


def scratch(path: str, cwd: str = "") -> bool:
    """Whether writing path changes nothing of the person's."""
    raw = (path or "").strip()
    if raw.startswith(SINKS) or raw == "-" or raw.lower() in WINDOWS_SINKS:
        return True
    p = expand(raw, cwd)
    if p is None:
        return False
    if p.startswith(SINKS):
        return True
    for d in scratch_dirs():
        if "*" in d:
            star = _norm(d)
            if fnmatch.fnmatch(_norm(p), star) or fnmatch.fnmatch(_norm(p), star + _mod().sep + "*"):
                return True
        elif under(p, d):
            return True
    return False
