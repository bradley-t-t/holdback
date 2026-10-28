"""Small terminal helpers for setup, doctor and uninstall. Standard library only."""

from __future__ import annotations

import os
import sys

from . import system


def color_on(stream=None) -> bool:
    stream = stream or sys.stdout
    if os.environ.get("NO_COLOR") or os.environ.get("TERM") == "dumb":
        return False
    return hasattr(stream, "isatty") and stream.isatty() and system.ansi_colors()


def _c(code: str, text: str) -> str:
    return "\033[%sm%s\033[0m" % (code, text) if color_on() else text


def bold(t): return _c("1", t)
def dim(t): return _c("2", t)
def green(t): return _c("32", t)
def yellow(t): return _c("33", t)
def red(t): return _c("31", t)
def cyan(t): return _c("36", t)


def interactive() -> bool:
    return sys.stdin.isatty() and sys.stdout.isatty()


def heading(text: str) -> None:
    print()
    print(bold(text))


def ask(prompt: str, default: str = "") -> str:
    hint = " [%s]" % default if default else ""
    try:
        got = input("%s%s: " % (prompt, dim(hint))).strip()
    except EOFError:
        got = ""
    return got or default


def confirm(prompt: str, default: bool = True) -> bool:
    hint = "Y/n" if default else "y/N"
    while True:
        try:
            got = input("%s %s " % (prompt, dim("[%s]" % hint))).strip().lower()
        except EOFError:
            return default
        if not got:
            return default
        if got in ("y", "yes"):
            return True
        if got in ("n", "no"):
            return False
