"""The `holdback` command.

    holdback setup                  put the hooks in ~/.claude/settings.json
    holdback doctor                 check everything and say what to fix
    holdback status                 whether the hooks are installed
    holdback update                 bring this copy up to date now
    holdback uninstall              take the hooks out again
    holdback classify "<message>"   what the judge makes of one message
    holdback changes <tool> '<json>'  what a call would change, or "reads only"
    holdback appeal "<command>"     whether the appeal judge says it only reads
    holdback selftest               the saved messages and commands, through the real judges

With no arguments it is the hook itself, reading Claude Code's JSON on stdin, which is how
a checkout and the plugin run it.
"""

from __future__ import annotations

import argparse
import json
import os
import sys

from . import __version__
from .claude import settings
from .commands import doctor, selftest, setup, uninstall, update


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="holdback",
        description="An AI assistant does work only when you told it to.")
    p.add_argument("--version", action="version", version="holdback " + __version__)
    sub = p.add_subparsers(dest="cmd")

    setup.add_arguments(sub.add_parser("setup", help="Put the hooks in Claude Code's settings"))
    d = sub.add_parser("doctor", help="Check everything and say what to fix")
    d.add_argument("--settings", help="Claude Code settings file")
    update.add_arguments(sub.add_parser("update", help="Bring this copy up to date"))
    uninstall.add_arguments(sub.add_parser("uninstall", help="Take Holdback's hooks out again"))
    selftest.add_arguments(sub.add_parser("selftest", help="Run the saved messages through the judges"))
    s = sub.add_parser("status", help="Show whether the hooks are installed")
    s.add_argument("--settings", help="Claude Code settings file")

    c = sub.add_parser("classify", help="What the judge makes of one message")
    c.add_argument("message")
    c.add_argument("--before", default="", help="The assistant's reply before it")
    ch = sub.add_parser("changes", help="What a tool call would change")
    ch.add_argument("tool")
    ch.add_argument("input", nargs="?", default="", help="The call's input as JSON, or a command")
    a = sub.add_parser("appeal", help="Whether the appeal judge says a command only reads")
    a.add_argument("command")

    w = sub.add_parser("warm", help=argparse.SUPPRESS)   # started by the UserPromptSubmit hook
    w.add_argument("transcript")
    w.add_argument("session")
    w.add_argument("digest")
    sub.add_parser("hook", help=argparse.SUPPRESS)       # the hook, for an explicit call
    sub.add_parser("version", help="Print the version")
    return p


def main(argv: list | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if not argv:
        from .hooks import main as hook
        return hook()
    parser = build_parser()
    args = parser.parse_args(argv)
    if getattr(args, "settings", None) and args.cmd != "setup":
        os.environ["CLAUDE_SETTINGS"] = args.settings
    commands = {
        "setup": setup.run,
        "doctor": doctor.run,
        "update": update.run,
        "uninstall": uninstall.run,
        "selftest": selftest.run,
        "status": _status,
        "classify": _classify,
        "changes": _changes,
        "appeal": _appeal,
        "warm": _warm,
        "hook": _hook,
        "version": _version,
    }
    if args.cmd not in commands:
        parser.print_help()
        return 2
    return commands[args.cmd](args)


def _status(args) -> int:
    from . import config
    print(json.dumps({**settings.status(), "settings": str(config.config_path()),
                      "state": str(config.state_dir()), "version": __version__}, indent=2))
    return 0


def _classify(args) -> int:
    from .judge import judge
    print(json.dumps(judge(args.message, args.before).as_dict(), indent=2))
    return 0


def _changes(args) -> int:
    from .changes import changes
    from .hooks.gate import appealable
    from .unknown import Unknown
    try:
        inp = json.loads(args.input) if args.input else {}
    except ValueError:
        inp = {"command": args.input}
    if not isinstance(inp, dict):
        inp = {"command": args.input}
    what = changes(args.tool, inp, os.getcwd())
    note = ""
    if isinstance(what, Unknown):
        note = (" (unrecognized: appealable)" if appealable(args.tool, what, inp.get("command") or "")
                else " (unrecognized)")
    print((what or "reads only") + note)
    return 0


def _appeal(args) -> int:
    from .judge import appeal
    print(json.dumps(appeal(args.command).as_dict(), indent=2))
    return 0


def _warm(args) -> int:
    from .hooks.prompt import warm
    warm(args.transcript, args.session, args.digest)
    return 0


def _hook(args) -> int:
    from .hooks import main as hook
    return hook()


def _version(args) -> int:
    print(__version__)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
