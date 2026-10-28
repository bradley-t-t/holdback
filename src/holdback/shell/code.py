"""Code a command would run: a script it names, or a program passed inline.

What counts as a change is a list of named rules, one per kind of change, rather than one
long pattern: the refusal can then say which kind it is ("run code that would write files"),
and each rule can be read and tested on its own.

A program Holdback keeps no list for may still be a script it can read: its shebang says
which language, and then its own code decides, the same way foo.sh or foo.py would. Python
that only shells out reads as the commands it runs, so printing what `ls` says is no more a
change than `ls` is.
"""

from __future__ import annotations

import os
import re
import shutil
from pathlib import Path

from ..paths import expand
from ..unknown import Unknown, like
from .parse import positional


class Rules:
    """Named patterns for one language. The first that matches names the change."""

    def __init__(self, flags=0, **rules):
        self.rules = [(name.replace("_", " "), re.compile(pattern, flags))
                      for name, pattern in rules.items()]
        self.union = re.compile("|".join("(?:%s)" % p for _, p in rules.items()), flags)

    def match(self, code: str) -> str:
        """What the code would do, in a few words, or "" when it only reads."""
        for name, pattern in self.rules:
            if pattern.search(code or ""):
                return name
        return ""

    def search(self, code: str):
        return self.union.search(code or "")


PYTHON_WRITES = Rules(
    re.S,
    write_files=r"\bopen\s*\([^)]*,\s*(?:mode\s*=\s*)?['\"][^'\"]*[wax+]"
                r"|(?<!stdout)(?<!stderr)\.write(?:lines)?\s*\(|\.write_(?:text|bytes)\s*\("
                r"|\.(?:unlink|rmdir|mkdir|touch|symlink_to|hardlink_to|chmod|lchmod)\s*\("
                r"|\bos\.(?:remove|unlink|rmdir|removedirs|rename|renames|replace|mkdir|makedirs|chmod|chown|"
                r"lchown|symlink|link|truncate|utime|mkfifo|mknod)\b"
                r"|\bshutil\.(?!which\b|get_terminal_size\b|disk_usage\b)\w+"
                r"|\b(?:json|pickle|yaml|toml|marshal)\.dump\s*\(|\bnp\.save"
                r"|\.to_(?:csv|json|excel|parquet|pickle|sql)\s*\(|\.savefig\s*\(|\.save\s*\(",
    run_commands=r"\bsubprocess\b|\bPopen\b|\bpty\.|\bmultiprocessing\b"
                 r"|\bos\.(?:system|popen|exec\w*|spawn\w*|fork|kill|killpg)\b",
    send_a_request=r"\brequests\.(?:post|put|patch|delete|request)\b|\bhttpx\.(?:post|put|patch|delete)\b"
                   r"|\burlopen\s*\([^)]*data\s*=|\bmethod\s*=\s*['\"](?:POST|PUT|PATCH|DELETE)\b"
                   r"|\bsmtplib\b|\bftplib\b|\bsocket\.socket\b|\bparamiko\b",
    open_a_database=r"\bsqlite3\.connect\b|\bpsycopg|\bpymysql\b",
    run_code_it_builds=r"(?<![.\w])(?:exec|eval|compile|__import__)\s*\(|\bimportlib\b|\bctypes\b|\bwebbrowser\b",
    change_the_environment=r"\bos\.environ\s*\[[^\]]*\]\s*=(?!=)|\bos\.environ\.(?:update|setdefault|pop)\b"
                           r"|\bos\.putenv\b",
)

NODE_WRITES = Rules(
    0,
    write_files=r"\.(?:writeFile|appendFile|unlink|rmdir|mkdir|rename|copyFile|rm|cp|chmod|chown|symlink|truncate|"
                r"createWriteStream|utimes)(?:Sync)?\s*\("
                r"|\bfs\w*\.(?:write|append|unlink|rm|rmdir|mkdir|rename|copy|cp|chmod|chown|symlink|link|truncate|"
                r"createWriteStream|utimes|mkdtemp)\w*|\bBun\.write\b|\bDeno\.(?:write|remove|mkdir|rename)\b",
    run_commands=r"\bchild_process\b|\b(?:execSync|execFileSync|spawnSync|exec|execFile|spawn|fork)\s*\("
                 r"|\bprocess\.kill\b|\bBun\.spawn\b|\bDeno\.(?:run|Command)\b",
    send_a_request=r"\bmethod\s*:\s*['\"](?:POST|PUT|PATCH|DELETE)"
                   r"|\brequire\(\s*['\"](?:net|http|https|dgram|cluster)['\"]",
)

PERL_WRITES = Rules(
    0,
    write_files=r"\b(?:unlink|rename|mkdir|rmdir|chmod|chown|symlink|link|utime|truncate)\b"
                r"|\bopen\s*\(?[^;]*['\"]\s*(?:>|\+<|\|)",
    run_commands=r"\b(?:system|exec|kill|qx)\b|`",
)

RUBY_WRITES = Rules(
    0,
    write_files=r"\bFile\.(?:write|delete|unlink|rename|open\([^)]*['\"][wa])|\bFileUtils\b",
    run_commands=r"\bsystem\b|\bexec\b|`|%x|\bIO\.popen\b|\bspawn\b",
    send_a_request=r"\bNet::HTTP::(?:Post|Put|Patch|Delete)\b",
)

# Scripts Holdback knows: which first arguments of each only read.
SCRIPT_READS = {"tether.py": {None, "check", "wait", "hold", "judge", "selftest"}}
# Holdback's own hooks, and Tether's, which change nothing of the person's.
QUIET_SCRIPTS = {"holdback.py", "guard-claude-md.py"}

# Python that shells out: the command it runs decides, the way it would on its own.
PY_RUN = re.compile(r"\b(?:subprocess\.(?:run|check_output|check_call|call|Popen)|os\.(?:system|popen))\s*\(")
STR_LIT = re.compile(r"[rbfu]{0,2}(?:'''(.*?)'''|\"\"\"(.*?)\"\"\"|'([^'\n]*)'|\"([^\"\n]*)\")", re.S)
# What is left of `subprocess` once the calls themselves are cut out: the constants, the
# exceptions and the import, none of which run anything.
PY_RUN_REST = re.compile(r"\bsubprocess\.(?:PIPE|STDOUT|DEVNULL|CalledProcessError|TimeoutExpired|CompletedProcess|"
                         r"SubprocessError|list2cmdline)\b|\bimport\s+subprocess\b|\bfrom\s+subprocess\s+import[^\n]*")

SHEBANG = re.compile(r"^#!([^\n]{0,300})")
SHEBANG_KINDS = {"sh": "shell", "bash": "shell", "zsh": "shell", "dash": "shell", "ksh": "shell",
                 "node": "node", "bun": "node", "deno": "node"}
LANGUAGES = {"python": PYTHON_WRITES, "node": NODE_WRITES}
PYTHON = re.compile(r"python(?:\d+(?:\.\d+)?)?|pypy\d*")
NOT_A_SCRIPT = object()
MAX_SCRIPT = 1 << 20


def _bash_change(cmd, here, depth, **kw):
    """What a shell command would change. Imported here because the shell reader and the
    code it reads each run the other."""
    from . import bash_change
    return bash_change(cmd, here, depth, **kw)


def call_args(code: str, at: int) -> str:
    """What is between the parentheses of a call whose "(" is at `at`."""
    depth, i, q = 0, at, ""
    while i < len(code):
        c = code[i]
        if q:
            if c == "\\":
                i += 2
                continue
            if code.startswith(q, i):
                i, q = i + len(q), ""
                continue
        elif c in "\"'":
            q = c * 3 if code.startswith(c * 3, i) else c
            i += len(q)
            continue
        elif c in "([{":
            depth += 1
        elif c in ")]}":
            depth -= 1
            if depth == 0:
                return code[at + 1:i]
        i += 1
    return ""


def first_arg(inside: str) -> str:
    """The first argument of a call, so a keyword argument's string isn't read as a
    command."""
    depth, i, q = 0, 0, ""
    while i < len(inside):
        c = inside[i]
        if q:
            if c == "\\":
                i += 2
                continue
            if inside.startswith(q, i):
                i, q = i + len(q), ""
                continue
        elif c in "\"'":
            q = c * 3 if inside.startswith(c * 3, i) else c
            i += len(q)
            continue
        elif c in "([{":
            depth += 1
        elif c in ")]}":
            depth -= 1
        elif c == "," and depth == 0:
            return inside[:i]
        i += 1
    return inside


def code_runs(code: str, here: str, depth: int):
    """What the commands Python shells out to would change, "" when a command isn't written
    out in full, or None when every one of them only reads and nothing else in the code
    writes."""
    rest, commands = code, []
    for m in PY_RUN.finditer(code):
        inside = call_args(code, m.end() - 1)
        rest = rest.replace(code[m.start():m.end() + len(inside) + 1], " ", 1)
        arg = first_arg(inside)
        words = [g for lit in STR_LIT.finditer(arg) for g in lit.groups() if g is not None]
        if not words or re.search(r"[^\s\[\](),+]", STR_LIT.sub(" ", arg)):
            return ""                # a variable, a call, an f-string: the command isn't all here
        commands.append(" ".join(words))
    if PYTHON_WRITES.search(PY_RUN_REST.sub(" ", rest)):
        return ""                    # the code writes on its own account too
    for cmd in commands:
        what = _bash_change(cmd, here, depth + 1)
        if what:
            return what
    return None


def code_change(code: str, rules: Rules, name: str = "", here: str = "", depth: int = 0):
    """What code would change, read by rules. name is the script it came from, when it came
    from one."""
    code = code or ""
    does = rules.match(code)
    if not does:
        return None
    if rules is PYTHON_WRITES and PY_RUN.search(code):
        inner = code_runs(code, here, depth)
        if inner is None:
            return None
        if inner:
            return like(inner, "run %s, which would %s" % (name, inner) if name
                        else "run code that would %s" % inner)
    return Unknown("run %s, which would %s" % (name, does) if name else "run code that would %s" % does)


def script_change(path: str, args: list, here: str, depth: int, kind: str):
    """A script run by path: read it, and judge what its code does."""
    name = os.path.basename(path)
    if name in SCRIPT_READS:
        pos = positional(args)
        return None if (pos[0] if pos else None) in SCRIPT_READS[name] else Unknown("run %s %s" % (name, pos[0]))
    if name in QUIET_SCRIPTS:
        return None
    full = expand(path, here)
    try:
        text = Path(full).read_text(errors="replace") if full and os.path.getsize(full) < MAX_SCRIPT else None
    except OSError:
        text = None
    if text is None:
        return Unknown("run %s" % name)
    if kind == "shell":
        inner = _bash_change(text, here, depth + 1)
        return like(inner, "run %s, which would %s" % (name, inner)) if inner else None
    return code_change(text, LANGUAGES[kind], name, here, depth)


def script_on_path(word: str, args: list, here: str, depth: int):
    """What a program Holdback has no list for would change, when it turns out to be a
    script it can read: None when the script only reads. NOT_A_SCRIPT for a binary, a program
    that isn't there, and one written in a language Holdback doesn't read."""
    if depth > 2:
        return NOT_A_SCRIPT
    full = expand(word, here) if ("/" in word or "\\" in word) else shutil.which(word)
    try:
        with open(full, "rb") as f:
            head = f.read(2048)
    except (OSError, TypeError, ValueError):
        return NOT_A_SCRIPT
    m = SHEBANG.match(head.decode("utf-8", "replace"))
    words = m.group(1).split() if m else []
    if words and os.path.basename(words[0]) == "env":
        words = [w for w in words[1:] if not w.startswith("-") and "=" not in w]
    name = os.path.basename(words[0]) if words else ""
    kind = "python" if PYTHON.fullmatch(name) else SHEBANG_KINDS.get(name)
    return script_change(full, args, here, depth, kind) if kind else NOT_A_SCRIPT
