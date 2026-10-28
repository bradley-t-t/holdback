"""`holdback uninstall`: take the hooks out, and with --purge or --all, Holdback's own
files. --all also removes the PATH entry the installer added and the holdback command
itself. On Windows the command is removed just after this process exits, since Windows
won't delete a running program."""

from __future__ import annotations

import os
import shlex
import shutil
import sys
from pathlib import Path

from .. import package, system, ui
from ..claude import settings
from ..config import config_dir, config_path, state_dir


def add_arguments(p) -> None:
    p.add_argument("--purge", action="store_true", help="Also delete Holdback's settings, verdicts and log")
    p.add_argument("--all", action="store_true",
                   help="Everything --purge does, then remove the holdback command itself")
    p.add_argument("-y", "--yes", action="store_true", help="Don't ask before deleting")
    p.add_argument("--settings", help="Claude Code settings file")


def data_paths() -> list:
    """Holdback's own settings and state folders, and the config file itself when
    HOLDBACK_CONFIG put it somewhere else."""
    out = []
    for p in (config_dir(), state_dir(), config_path()):
        if p not in out and not any(parent in out for parent in p.parents):
            out.append(p)
    return out


def purge(paths: list) -> list:
    """Delete the given files and folders that exist. Returns what was removed."""
    removed = []
    for p in paths:
        if p.is_dir() and not p.is_symlink():
            shutil.rmtree(p)
        elif p.exists() or p.is_symlink():
            p.unlink()
        else:
            continue
        removed.append(str(p))
    return removed


def run(args) -> int:
    if getattr(args, "settings", None):
        os.environ["CLAUDE_SETTINGS"] = args.settings
    remove = package.removal_command()
    remove_text = " ".join(shlex.quote(x) for x in remove)

    path = settings.uninstall()
    print("Removed Holdback's hooks from %s" % path)
    if args.purge or args.all:
        code = _purge(path, args.yes)
        if code is not None:
            return code
    else:
        print("Settings and verdicts are still in %s. `holdback uninstall --purge` deletes them."
              % config_dir())

    if not remove:
        return 0
    if not args.all:
        print("To remove the holdback command too: %s" % remove_text)
        print("Or run `holdback uninstall --all` to do everything in one step.")
        return 0
    program = shutil.which(remove[0]) or package.tool(remove[0])
    if not program:
        _remove_path_lines()
        print("Last step, remove the holdback command: %s" % remove_text)
        return 0
    if not args.yes and not ui.confirm("Remove the holdback command now (%s)?" % remove_text, True):
        print("Kept it. To remove it later: %s" % remove_text)
        return 0
    _remove_path_lines()
    if system.windows():
        system.run_after_exit([[program] + remove[1:]])
        print("Removing the holdback command in a few seconds: %s" % remove_text)
        return 0
    print("Running: %s" % remove_text)
    sys.stdout.flush()
    sys.stderr.flush()
    os.execvp(remove[0], remove)     # replaces this process, so holdback can remove itself
    return 0


def _remove_path_lines() -> None:
    for f in package.remove_path_lines():
        print("Removed the PATH entry Holdback added in %s" % f)


def _purge(settings_file: Path, yes: bool):
    """Delete settings, verdicts, the log and the settings backups. Returns an exit code to
    stop with, or None to carry on."""
    targets = [q for q in data_paths() if q.exists()] + settings.backups(settings_file)
    if not targets:
        print("No Holdback settings or verdicts to delete.")
        return None
    print("This deletes:")
    for q in targets:
        print("  %s" % q)
    if not yes:
        if not ui.interactive():
            print("Pass --yes to delete them without a prompt.", file=sys.stderr)
            return 1
        if not ui.confirm("Delete these?", False):
            print("Kept them.")
            return 0
    for q in purge(targets):
        print("Deleted %s" % q)
    return None
