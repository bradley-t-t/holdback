"""`holdback update`: check main for a newer Holdback and install it now.

`--check` only reports. `--auto` is the background check the hooks start, at most once a
minute (see holdback.update); it prints nothing.
"""

from __future__ import annotations

import argparse
import sys

from .. import package, system, ui
from .. import update as updater


def add_arguments(p) -> None:
    p.add_argument("--check", action="store_true", help="Only say whether a newer version is there")
    # The background check the hooks start: it prints nothing, so it isn't offered.
    p.add_argument("--auto", action="store_true", help=argparse.SUPPRESS)


def run(args) -> int:
    try:
        result = updater.update(check_only=args.check)
    except updater.Busy:
        if not args.auto:
            print("Another update is already running.", file=sys.stderr)
        return 0 if args.auto else 1
    except Exception as e:  # noqa: BLE001
        if args.auto:
            return 1                 # the failure is already in update.json and the log
        print(ui.red("Update failed:") + " %s: %s" % (type(e).__name__, e), file=sys.stderr)
        if not package.upgrade_command():
            print("Reinstall with: " + package.install_command(), file=sys.stderr)
        return 1
    if args.auto:
        return 0
    current, latest = result.current, result.latest
    if result.upgraded and system.windows() and package.installer() != "git":
        print(ui.green("Updating") + " Holdback %s -> %s. It finishes a few seconds after this "
              "command exits, and the next prompt uses it." % (current, latest))
    elif result.upgraded:
        print(ui.green("Updated") + " Holdback %s -> %s. The next prompt uses it." % (current, latest))
    elif updater.is_newer(latest, current):
        held_back = package.checkout_held_back()
        if held_back and not args.check:
            print("Holdback %s is available (this is %s), but %s." % (latest, current, held_back))
        else:
            print("Holdback %s is available (this is %s). Run `holdback update` to install it."
                  % (latest, current))
    else:
        print("Holdback %s is the newest on %s." % (current, package.BRANCH))
    return 0
