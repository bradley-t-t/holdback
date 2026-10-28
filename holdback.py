#!/usr/bin/env python3
"""Run Holdback straight from a checkout, with nothing installed.

This is what the plugin's hooks and cloud-setup.sh run, and what an older install put in
~/.claude/settings.json. With no arguments it is the hook, reading Claude Code's JSON on
stdin; with arguments it is the `holdback` command (see src/holdback/cli.py).
"""

import os
import sys

SRC = os.path.join(os.path.dirname(os.path.abspath(__file__)), "src")
sys.path.insert(0, SRC)

if __name__ == "__main__":
    from holdback.cli import main

    sys.exit(main() or 0)
else:
    # Python is importing this file as the module "holdback", because the folder it sits in
    # happens to be on the path: the installed hook runs as `python -m holdback.hooks`, and
    # a hook runs wherever the session is, which may well be this checkout. This file isn't
    # the package, so hand the name to the real one in src/ and step out of the way.
    import importlib

    del sys.modules[__name__]
    sys.modules[__name__] = importlib.import_module("holdback")
