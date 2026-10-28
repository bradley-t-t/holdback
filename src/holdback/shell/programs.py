"""What one program would change: the lists of programs that only read, the ones that change
only the paths they name, and a handler for each program whose arguments decide.

A handler takes (prog, args, here, body, depth) and answers what running it would change, in
a few words, or None when it only reads. A program with no handler and no list is read as the
script it is where it can be (see code.py), and is otherwise Unknown - held, but appealable.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

from .. import sql
from ..paths import expand, scratch
from ..unknown import Unknown
from .code import (NODE_WRITES, NOT_A_SCRIPT, PERL_WRITES, PYTHON, PYTHON_WRITES, RUBY_WRITES,
                   code_change, script_change, script_on_path)
from .parse import ASSIGN, HEADERS, KEYWORDS, positional

READ_PROGS = set("""
ls cat head tail less more bat batcat grep egrep fgrep zgrep rg ag ack wc cut tr nl column paste join comm diff
cmp file stat du df pwd echo printf true false test [ [[ ]] which type whereis whence hash printenv date cal
uname whoami id groups hostname sw_vers uptime ps pgrep top htop lsof netstat ss ping dig nslookup host
traceroute whois tree realpath readlink dirname basename md5 md5sum shasum sha1sum sha256sum sha512sum cksum
xxd hexdump od strings jq gron mdfind mdls locate man apropos info sleep wait cd pushd popd dirs export
unset set shopt read let declare typeset local shift return exit break continue trap umask alias unalias
seq yes expr bc dc tac rev fold fmt expand unexpand iconv base64 zcat bzcat xzcat zless lsblk free
vm_stat system_profiler ioreg log journalctl nproc getconf locale tty stty clear tput open say afplay
pbcopy pbpaste mktemp : identify ffprobe mediainfo pdfinfo otool nm lipo size file jless fx csvlook
pytest py.test jest vitest mocha ava phpunit rspec flake8 pylint mypy pyright pyflakes shellcheck hadolint
actionlint yamllint jsonlint htmlhint gitleaks semgrep bandit vulture radon cloc tokei scc hyperfine
systeminfo hostnamectl ver where findstr tasklist whoami.exe
""".split())

# Programs that change only the paths they name: fine when every one is in the scratchpad.
PATH_VERBS = {"rm": "delete", "rmdir": "delete", "unlink": "delete", "shred": "delete", "srm": "delete",
              "trash": "delete", "touch": "create", "mkdir": "create", "mkfifo": "create", "chmod": "change",
              "chown": "change", "chgrp": "change", "chflags": "change", "truncate": "change", "setfile": "change",
              "cp": "copy files to", "ln": "link files in", "install": "install files in", "ditto": "copy files to",
              "rsync": "copy files to", "scp": "copy files to", "mv": "move", "patch": "patch files in"}
PATH_OPTS = {"touch": {"-t", "-d", "-r"}, "truncate": {"-s", "-r"}, "install": {"-m", "-o", "-g", "-t", "-S"},
             "cp": {"-t"}, "mv": {"-t"}, "ln": {"-t"}, "mkdir": {"-m"}, "patch": {"-p", "-i", "-o", "-d", "-B", "-z"},
             "scp": {"-P", "-i", "-o", "-F", "-c", "-l", "-J", "-S", "-D", "-X"},
             "rsync": {"-e", "--rsh", "--exclude", "--include", "--filter", "-f", "--rsync-path", "--exclude-from",
                       "--include-from", "--files-from", "--chmod", "--chown", "--log-file", "--backup-dir",
                       "--partial-dir", "--temp-dir", "-T", "--compare-dest", "--link-dest", "--port", "--timeout"}}

PY_MODULE_READS = {"pytest", "unittest", "json.tool", "py_compile", "compileall", "pydoc", "timeit", "doctest",
                   "mypy", "pyflakes", "flake8", "pylint", "tabnanny", "site", "sysconfig", "platform", "tokenize",
                   "ast", "dis", "calendar", "this", "pstats", "pyright", "coverage", "tomllib"}

TEST_SCRIPTS = {"test", "tests", "lint", "typecheck", "type-check", "check", "tsc", "validate", "format:check",
                "lint:check", "test:unit", "test:ci", "fmt:check"}


def _bash(cmd, here, depth, **kw):
    """What a shell command would change. Imported here because a program's handler and the
    shell reader each run the other."""
    from . import bash_change
    return bash_change(cmd, here, depth, **kw)


def remote_path(p: str) -> str:
    """The path in host:path, or p itself."""
    return p.split(":", 1)[1] if re.match(r"^[\w.@-]+:", p) and not p.startswith("/") else p


def paths_change(prog: str, args: list, here: str):
    if prog == "patch" and any(a in ("--dry-run", "-C", "--check") for a in args):
        return None
    if prog == "rsync" and any(a in ("-n", "--dry-run", "--list-only") or (re.fullmatch(r"-[a-zA-Z]+", a) and "n" in a)
                               for a in args):
        return None
    pos = positional(args, PATH_OPTS.get(prog, ()))
    target = next((args[i + 1] for i, a in enumerate(args[:-1]) if a in ("-t", "--target-directory")), None)
    if prog in ("chmod", "chown", "chgrp", "chflags") and not any(a.startswith("--reference") for a in args):
        pos = pos[1:]               # the mode or owner
    if prog in ("cp", "ln", "install", "ditto", "rsync", "scp"):
        pos = [target] if target else pos[-1:]
    if prog == "patch":
        pos = pos[:1] or ([here] if here else [""])
    bad = [p for p in pos if not scratch(remote_path(p), here)]
    if not pos and prog not in ("patch",):
        return None
    return "%s %s" % (PATH_VERBS[prog], bad[0] or "files") if bad else None


# ---------------------------------------------------------------- interpreters

def python_change(prog, args, here, body, depth):
    i = 0
    while i < len(args):
        a = args[i]
        if a == "-c" or re.fullmatch(r"-[IBdEhiOqsSuvx]+c", a):
            return code_change(args[i + 1] if i + 1 < len(args) else "", PYTHON_WRITES)
        if a == "-m":
            return module_change(args[i + 1] if i + 1 < len(args) else "", args[i + 2:], here, body, depth)
        if a in ("-W", "-X", "-Q"):
            i += 2
            continue
        if a == "-":
            return code_change(body or "", PYTHON_WRITES)
        if a.startswith("-"):
            if a in ("-V", "--version", "-h", "--help"):
                return None
            i += 1
            continue
        return script_change(a, args[i + 1:], here, depth, "python")
    return code_change(body or "", PYTHON_WRITES)


def module_change(mod, args, here, body, depth):
    if mod in PY_MODULE_READS:
        return None
    if mod in ("pip", "pip3"):
        return sub_change("pip", args)
    if mod in ("black", "isort", "ruff", "autopep8", "yapf"):
        return command_change([mod] + args, here, body, depth)
    if mod == "venv":
        pos = positional(args, {"--prompt"})
        return None if pos and all(scratch(p, here) for p in pos) else "create a virtual environment"
    return Unknown("run python -m %s" % mod)


def node_change(prog, args, here, body, depth):
    i = 0
    while i < len(args):
        a = args[i]
        if a in ("-e", "--eval", "-p", "--print"):
            return code_change(args[i + 1] if i + 1 < len(args) else "", NODE_WRITES)
        if a in ("--check", "-c", "-v", "--version", "-h", "--help"):
            return None
        if a in ("-r", "--require", "--import", "--loader", "--input-type", "--env-file", "--conditions", "-C"):
            i += 2
            continue
        if a == "-":
            return code_change(body or "", NODE_WRITES)
        if a.startswith("-"):
            i += 1
            continue
        return script_change(a, args[i + 1:], here, depth, "node")
    return code_change(body or "", NODE_WRITES)


def shell_change(prog, args, here, body, depth):
    i = 0
    while i < len(args):
        a = args[i]
        if a == "-c" or (re.fullmatch(r"-[a-zA-Z]+", a) and "c" in a):
            return _bash(args[i + 1] if i + 1 < len(args) else "", here, depth + 1)
        if a == "-n" or (re.fullmatch(r"-[a-zA-Z]+", a) and "n" in a):
            return None              # a syntax check
        if a in ("-s", "-"):
            return _bash(body or "", here, depth + 1)
        if a in ("-o", "+o", "-O", "+O"):
            i += 2
            continue
        if a.startswith(("-", "+")):
            i += 1
            continue
        return script_change(a, args[i + 1:], here, depth, "shell")
    return _bash(body or "", here, depth + 1)


def ssh_change(prog, args, here, body, depth):
    i = 0
    while i < len(args):
        a = args[i]
        if a == "--":
            i += 1
            break
        if a.startswith("-") and len(a) > 1:
            i += 2 if len(a) == 2 and a[1] in "BbcDEeFIiJLlmOoPpQRSWw" else 1
            continue
        break
    if i >= len(args):
        return "open a shell on another machine"
    remote = args[i + 1:]
    if not remote:
        return _bash(body, "", depth + 1) if body else "open a shell on another machine"
    return _bash(" ".join(remote), "", depth + 1, stdin=body)


# ---------------------------------------------------------------- version control

def git_change(prog, args, here, body, depth):
    i = 0
    while i < len(args) and args[i].startswith("-"):
        i += 2 if args[i] in ("-C", "-c", "--git-dir", "--work-tree", "--namespace", "--super-prefix",
                              "--config-env") else 1
    if i >= len(args):
        return None
    sub, rest = args[i], args[i + 1:]
    flags = [a for a in rest if a.startswith("-")]
    pos = positional(rest)
    if sub in ("status", "log", "diff", "show", "rev-parse", "rev-list", "ls-files", "ls-tree", "ls-remote", "blame",
               "annotate", "grep", "describe", "shortlog", "cat-file", "name-rev", "merge-base", "for-each-ref",
               "count-objects", "fsck", "check-ignore", "check-attr", "check-ref-format", "var", "help", "version",
               "whatchanged", "range-diff", "cherry", "show-ref", "show-branch", "verify-commit", "verify-tag", "fetch",
               "difftool", "diff-tree", "diff-files", "diff-index", "get-tar-commit-id"):
        out = next((a.split("=", 1)[1] for a in rest if a.startswith("--output=")), None)
        return "write %s" % out if out and not scratch(out, here) else None
    if sub == "branch":
        if any(f in ("-d", "-D", "--delete", "-m", "-M", "--move", "-c", "-C", "--copy", "-u", "--unset-upstream",
                     "--edit-description", "-f", "--force", "-t", "--track", "--no-track")
               or f.startswith(("--set-upstream-to", "--track=")) for f in flags):
            return "change git branches"
        listing = any(f in ("-l", "--list", "-a", "--all", "-r", "--remotes") or
                      f.startswith(("--contains", "--no-contains", "--merged", "--no-merged", "--points-at"))
                      for f in flags)
        return "create a git branch" if pos and not listing else None
    if sub == "tag":
        if any(f in ("-d", "--delete", "-a", "--annotate", "-s", "--sign", "-u", "-f", "--force", "-m", "-F", "-e",
                     "--edit") for f in flags):
            return "change git tags"
        listing = any(f in ("-l", "--list", "-v", "--verify", "-n") or
                      f.startswith(("--contains", "--no-contains", "--merged", "--no-merged", "--points-at", "-n"))
                      for f in flags)
        return "create a git tag" if pos and not listing else None
    if sub == "remote":
        return None if not pos or pos[0] in ("show", "get-url") else "change git remotes"
    if sub == "config":
        pos = positional(rest, {"-f", "--file", "--blob", "--type", "--default", "--comment"})
        writes = any(f in ("--unset", "--unset-all", "--add", "--replace-all", "--rename-section", "--remove-section",
                           "-e", "--edit") for f in flags)
        if writes or (pos and pos[0] in ("set", "unset", "rename-section", "remove-section", "edit")) or \
                (len(pos) >= 2 and pos[0] not in ("get", "list")):
            return "change git config"
        return None
    if sub == "stash":
        return None if pos and pos[0] in ("list", "show") else "change the git stash"
    if sub == "worktree":
        return None if pos and pos[0] == "list" else "change git worktrees"
    if sub == "reflog":
        return None if not pos or pos[0] in ("show", "exists") else "change the git reflog"
    if sub == "symbolic-ref":
        return None if len(pos) <= 1 and not {"-d", "--delete"} & set(flags) else "change a git ref"
    if sub in ("notes", "submodule", "bisect"):
        reads = {"notes": ("list", "show"), "submodule": ("status", "summary"), "bisect": ("log", "view", "visualize")}
        return None if (not pos and sub != "bisect") or (pos and pos[0] in reads[sub]) else "run git %s" % sub
    if sub == "archive":
        out = next((rest[k + 1] for k, a in enumerate(rest[:-1]) if a in ("-o", "--output")), None) or \
            next((a.split("=", 1)[1] for a in rest if a.startswith("--output=")), None)
        return "write %s" % out if out and not scratch(out, here) else None
    if sub in ("clone", "init"):
        pos = positional(rest, {"--depth", "-b", "--branch", "-o", "--origin", "-c", "--config", "--reference",
                                "--separate-git-dir", "-j", "--jobs", "--filter", "--template", "-u", "--upload-pack",
                                "--shallow-since", "--shallow-exclude", "--initial-branch"})
        dest = pos[1] if sub == "clone" and len(pos) > 1 else pos[0] if sub == "init" and pos else None
        return None if (scratch(dest, here) if dest else scratch(here)) else "run git %s" % sub
    return "run git %s" % sub


GH_READS = {"pr": {"view", "list", "status", "diff", "checks"}, "issue": {"view", "list", "status"},
            "repo": {"view", "list"}, "run": {"view", "list", "watch"}, "workflow": {"view", "list"},
            "release": {"view", "list"}, "gist": {"view", "list"}, "label": {"list"}, "search": None,
            "auth": {"status", "token"}, "status": None, "browse": None, "cache": {"list"}, "secret": {"list"},
            "variable": {"list", "get"}, "ruleset": {"list", "view", "check"},
            "project": {"list", "view", "field-list", "item-list"}, "codespace": {"list", "view", "logs"},
            "extension": {"list", "search", "browse"}, "alias": {"list"}, "config": {"get", "list"},
            "org": {"list"}, "help": None, "version": None, "--version": None, "completion": None}


def gh_change(prog, args, here, body, depth):
    pos = positional(args, {"-R", "--repo", "--hostname", "-q", "--jq", "-t", "--template", "-L", "--limit", "-s",
                            "--state", "-A", "--author", "-l", "--label", "-B", "--base", "-H", "--head", "-w",
                            "--workflow", "-b", "--branch", "-u", "--user", "-e", "--event", "-c", "--commit",
                            "--json", "-S", "--search", "-a", "--assignee", "-X", "--method", "-f", "-F", "--field",
                            "--raw-field", "--input", "--header", "--cache", "-p", "--preview"})
    if not args:
        return None
    if pos and pos[0] == "api":
        method = next((args[k + 1].upper() for k, a in enumerate(args[:-1]) if a in ("-X", "--method")), None)
        fields = any(a in ("-f", "-F", "--field", "--raw-field", "--input") or
                     a.startswith(("--field=", "--raw-field=", "--input=")) for a in args)
        if method in ("GET", "HEAD") or (method is None and not fields):
            return None
        if method is None and len(pos) > 1 and pos[1] == "graphql" and not any("mutation" in a for a in args):
            return None
        return "send a GitHub API request that changes something"
    group = pos[0] if pos else (args[0] if args[0] in GH_READS else "")
    if group in GH_READS:
        reads = GH_READS[group]
        if reads is None or (len(pos) > 1 and pos[1] in reads) or (len(pos) == 1 and group in ("status",)):
            return None
    return "run gh " + " ".join(pos[:2])


# ---------------------------------------------------------------- the network

def curl_change(prog, args, here, body, depth):
    method, data, get, outs = None, False, False, []
    takes = set("AbcdDeEFHKmoPrtTuUwxXyYzC")
    i = 0
    while i < len(args):
        a = args[i]
        nxt = args[i + 1] if i + 1 < len(args) else ""
        if a.startswith("--"):
            name, _, val = a.partition("=")
            given = bool(_)
            if name in ("--request",):
                method = (val if given else nxt).upper()
            elif name.startswith(("--data", "--form", "--json", "--upload-file")):
                data = True
            elif name == "--get":
                get = True
            elif name in ("--output", "--cookie-jar", "--dump-header", "--trace", "--trace-ascii", "--stderr"):
                outs.append(val if given else nxt)
            elif name in ("--remote-name", "--remote-name-all", "--remote-header-name"):
                outs.append(None)
            elif name == "--head":
                method = "HEAD"
            elif name == "--output-dir":
                outs.append((val if given else nxt) + "/x")
            i += 1 if given or name in ("--get", "--head", "--remote-name", "--remote-name-all",
                                        "--remote-header-name") or not nxt or nxt.startswith("-") else 2
            continue
        if a.startswith("-") and len(a) > 1:
            j = 1
            while j < len(a):
                f = a[j]
                if f in takes:
                    val = a[j + 1:] or nxt
                    if f == "X":
                        method = val.upper()
                    elif f in "dFT":
                        data = True
                    elif f in "ocD":
                        outs.append(val)
                    i += 1 if a[j + 1:] else 2
                    break
                if f == "G":
                    get = True
                elif f == "I":
                    method = "HEAD"
                elif f == "O":
                    outs.append(None)
                j += 1
            else:
                i += 1
            continue
        i += 1
    if method in ("POST", "PUT", "PATCH", "DELETE"):
        return "send a %s request" % method
    if data and not get and method not in ("GET", "HEAD"):
        return "send data to a URL"
    for o in outs:
        if o is None and not scratch(here or "."):
            return "download a file"
        if o is not None and o != "-" and not scratch(o, here):
            return "write %s" % o
    return None


def wget_change(prog, args, here, body, depth):
    if any(a in ("--spider", "-O-", "-qO-", "-O", "--output-document") for a in args):
        out = next((args[k + 1] for k, a in enumerate(args[:-1]) if a in ("-O", "--output-document")), None)
        if any(a in ("--spider", "-O-", "-qO-") for a in args) or out in ("-", None) or (out and scratch(out, here)):
            return None
    prefix = next((args[k + 1] for k, a in enumerate(args[:-1]) if a in ("-P", "--directory-prefix")), None)
    return None if (prefix and scratch(prefix, here)) or scratch(here or ".") else "download a file"


# ---------------------------------------------------------------- text tools

def sed_change(prog, args, here, body, depth):
    for a in args:
        if a == "--in-place" or a.startswith("--in-place=") or (re.match(r"^-[a-zA-Z]*i", a) and not a.startswith("--")):
            return "edit files in place"
    return None


def awk_change(prog, args, here, body, depth):
    if any(a in ("-i", "--include") for a in args) and "inplace" in args:
        return "edit files in place"
    pos = positional(args, {"-F", "-v", "-f", "--field-separator", "--assign"})
    program = pos[0] if pos else ""
    if re.search(r"\bsystem\s*\(|\|\s*getline|\bprint[f]?\b[^;{}]*?(?:>{1,2}|\|)\s*[\"$\w(]", program):
        return "run awk that writes files or runs commands"
    return None


def find_change(prog, args, here, body, depth):
    roots = []
    for a in args:
        if a.startswith(("-", "(", "!")):
            break
        roots.append(a)
    found = (roots[0] if roots else ".").rstrip("/") + "/found"    # where the files it finds are
    for k, a in enumerate(args):
        if a in ("-delete", "-fprint", "-fprint0", "-fprintf", "-fls"):
            return "delete or write files with find"
        if a in ("-exec", "-execdir", "-ok", "-okdir"):
            inner = []
            for b in args[k + 1:]:
                if b in (";", "+"):
                    break
                inner.append(b)
            what = command_change([found if b == "{}" else b for b in inner] or ["true"], here, None, depth)
            if what:
                return what
    return None


def xargs_change(prog, args, here, body, depth):
    i = 0
    takes = {"-n", "-I", "-L", "-P", "-s", "-d", "-E", "-a", "-i", "--max-args", "--replace", "--max-lines",
             "--max-procs", "--delimiter", "--eof", "--arg-file"}
    while i < len(args) and args[i].startswith("-"):
        i += 2 if args[i] in takes else 1
    return command_change((args[i:] or ["echo"]) + ["the-input"], here, None, depth)   # what it reads is unknown


def sort_change(prog, args, here, body, depth):
    out = next((args[k + 1] for k, a in enumerate(args[:-1]) if a == "-o"), None) or \
        next((a.split("=", 1)[1] for a in args if a.startswith("--output=")), None)
    return "write %s" % out if out and not scratch(out, here) else None


def uniq_change(prog, args, here, body, depth):
    pos = positional(args, {"-f", "-s", "-w", "--skip-fields", "--skip-chars", "--check-chars"})
    return "write %s" % pos[1] if len(pos) > 1 and not scratch(pos[1], here) else None


def tee_change(prog, args, here, body, depth):
    bad = [p for p in positional(args) if not scratch(p, here)]
    return "write %s" % bad[0] if bad else None


def dd_change(prog, args, here, body, depth):
    out = next((a[3:] for a in args if a.startswith("of=")), None)
    return "write %s" % out if out and not scratch(out, here) else None


# ---------------------------------------------------------------- archives

def tar_change(prog, args, here, body, depth):
    mode = (args[0].lstrip("-") if args else "") + "".join(a[1:] for a in args[1:] if re.fullmatch(r"-[a-zA-Z]+", a))
    if "t" in mode or "--list" in args:
        return None
    dest = next((args[k + 1] for k, a in enumerate(args[:-1]) if a in ("-C", "--directory")), None)
    archive = next((args[k + 1] for k, a in enumerate(args[:-1]) if a == "-f"), None)
    if "x" in mode:
        return None if scratch(dest or here or "") else "extract files"
    if archive and (archive == "-" or scratch(archive, here)):
        return None
    return "write an archive"


def unzip_change(prog, args, here, body, depth):
    if any(a in ("-l", "-v", "-t", "-Z", "-p", "-z", "-lv") for a in args):
        return None
    dest = next((args[k + 1] for k, a in enumerate(args[:-1]) if a == "-d"), None)
    return None if scratch(dest or here or "", here) else "extract files"


def packer_change(prog, args, here, body, depth):
    """zip, gzip, xz and the like: fine when they only write to stdout, list or test, or when
    every file they name is in the scratchpad."""
    if any(a in ("-c", "--stdout", "--to-stdout", "-l", "--list", "-t", "--test") or
           (re.fullmatch(r"-[a-zA-Z0-9]+", a) and set(a[1:]) & set("clt")) for a in args):
        return None
    pos = positional(args)
    return None if pos and all(scratch(p, here) for p in pos) else "write files with %s" % prog


# ---------------------------------------------------------------- databases

def sqlite_change(prog, args, here, body, depth):
    if "-readonly" in args:
        return None
    pos = positional(args, {"-cmd", "-separator", "-newline", "-nullvalue", "-init", "-vfs"})
    statements = " ".join(pos[1:]) or body or ""
    if not statements.strip():
        return "open a database shell"
    return None if sql.reads(statements) else "run SQL that changes data"


def psql_change(prog, args, here, body, depth):
    flag = "-e" if prog == "mysql" else "-c"
    sqls = [args[k + 1] for k, a in enumerate(args[:-1]) if a in (flag, "--command", "--execute")]
    files = [args[k + 1] for k, a in enumerate(args[:-1]) if a in ("-f", "--file")]
    for f in files:
        try:
            sqls.append(Path(expand(f, here) or "").read_text())
        except OSError:
            return "run SQL from a file"
    if body:
        sqls.append(body)
    if not sqls:
        return "open a database shell"
    return None if all(sql.reads(s) for s in sqls) else "run SQL that changes data"


# ---------------------------------------------------------------- build tools

def npm_change(prog, args, here, body, depth):
    pos = positional(args, {"--prefix", "-C", "--dir", "--filter", "-w", "--workspace", "--cwd"})
    sub = pos[0] if pos else ""
    rest = pos[1:]
    if not pos:
        return None if prog in ("npm", "pnpm", "bun") and args else "install packages"
    if sub in ("run", "run-script", "rs"):
        return None if rest and rest[0] in TEST_SCRIPTS else "run the " + (rest[0] if rest else "") + " script"
    if sub in ("exec", "x", "dlx"):
        return command_change(rest, here, body, depth) if rest else None
    if sub in TEST_SCRIPTS or sub in ("t", "tst"):
        return None
    if sub in ("ls", "list", "ll", "la", "view", "v", "info", "show", "outdated", "why", "explain", "search", "s",
               "doctor", "ping", "prefix", "root", "bin", "help", "whoami", "fund", "query", "licenses", "workspaces",
               "--version", "-v", "pm"):
        return None if not (sub == "pm" and rest and rest[0] not in ("ls", "hash", "bin", "cache")) \
            else "run %s pm" % prog
    if sub == "audit":
        return "fix packages" if "fix" in rest or "--fix" in args else None
    if sub == "version":
        return None if not rest else "bump the version"
    if sub == "config":
        return None if rest and rest[0] in ("get", "list", "ls") else "change the npm config"
    if sub == "pack" and "--dry-run" in args:
        return None
    if sub == "cache":
        return None if rest and rest[0] in ("ls", "list", "verify", "dir") else "change the package cache"
    if prog == "bun" and sub in ("test",):
        return None
    return "run %s %s" % (prog, sub)


def npx_change(prog, args, here, body, depth):
    i = 0
    while i < len(args) and args[i].startswith("-"):
        if args[i] in ("-c", "--call"):
            return _bash(args[i + 1] if i + 1 < len(args) else "", here, depth + 1)
        i += 2 if args[i] in ("-p", "--package") else 1
    return command_change(args[i:], here, body, depth) if args[i:] else None


def make_change(prog, args, here, body, depth):
    if any(a in ("-n", "--dry-run", "--just-print", "--recon", "-q", "--question", "-p", "--print-data-base")
           for a in args):
        return None
    targets = [a for a in positional(args, {"-C", "-f", "--file", "-l", "-o", "-W", "-I", "--directory"})
               if "=" not in a]
    return None if targets and all(t in ("test", "tests", "check", "lint", "typecheck", "help", "verify")
                                   for t in targets) else "run make " + " ".join(targets)


def cargo_change(prog, args, here, body, depth):
    pos = positional(args, {"-p", "--package", "--manifest-path", "-j", "--jobs", "--target", "--features", "-F"})
    sub = pos[0] if pos else ""
    if sub in ("test", "t", "check", "c", "tree", "metadata", "doc", "bench", "search", "verify-project", "version",
               "help", "locate-project", "pkgid", "read-manifest") or sub == "" or "--version" in args:
        return None
    if sub == "clippy":
        return "fix code with clippy" if "--fix" in args else None
    if sub == "fmt":
        return None if "--check" in args else "format code"
    return "run cargo %s" % sub


def go_change(prog, args, here, body, depth):
    pos = positional(args, {"-C", "-run", "-count", "-timeout", "-tags", "-p"})
    sub = pos[0] if pos else ""
    if sub in ("test", "vet", "list", "env", "version", "doc", "help", "") and not (sub == "env" and "-w" in args):
        return None
    if sub == "mod" and len(pos) > 1 and pos[1] in ("graph", "why", "verify"):
        return None
    return "run go %s" % sub


def deno_change(prog, args, here, body, depth):
    pos = positional(args)
    sub = pos[0] if pos else ""
    if sub in ("test", "check", "info", "doc", "bench", "") or "--version" in args:
        return None
    if sub == "lint":
        return "fix code with deno lint" if "--fix" in args else None
    if sub == "fmt":
        return None if "--check" in args else "format code"
    return "run deno %s" % sub


def formatter_change(prog, args, here, body, depth):
    """Formatters and linters that change files only when told to."""
    fixes = {"eslint": ("--fix",), "prettier": ("--write", "-w"), "stylelint": ("--fix",), "markdownlint": ("--fix",),
             "markdownlint-cli2": ("--fix",), "golangci-lint": ("--fix",), "standard": ("--fix",), "xo": ("--fix",),
             "rubocop": ("-a", "-A", "--autocorrect", "--auto-correct", "--autocorrect-all", "--auto-correct-all"),
             "swiftlint": ("--fix", "--autocorrect", "autocorrect"), "ktlint": ("-F", "--format"),
             "clang-format": ("-i",), "shfmt": ("-w", "--write"), "gofmt": ("-w",), "autopep8": ("-i", "--in-place"),
             "yapf": ("-i", "--in-place"), "biome": ("--write", "--apply", "--fix", "--apply-unsafe"),
             "sqlfluff": ("fix",)}
    if prog in fixes:
        return "fix files with %s" % prog if any(a in fixes[prog] or a.startswith(tuple(f + "=" for f in fixes[prog]))
                                                 for a in args) else None
    if prog == "black":
        return None if any(a in ("--check", "--diff", "--version") for a in args) else "format code with black"
    if prog == "isort":
        return None if any(a in ("--check-only", "--check", "-c", "--diff", "--version") for a in args) \
            else "sort imports with isort"
    if prog == "ruff":
        pos = positional(args)
        if pos and pos[0] == "format":
            return None if any(a in ("--check", "--diff") for a in args) else "format code with ruff"
        return "fix code with ruff" if any(a in ("--fix", "--unsafe-fixes") for a in args) else None
    if prog in ("tsc", "vue-tsc"):
        return None if any(a in ("--noEmit", "--version", "-v", "--help", "-h", "--showConfig", "--listFilesOnly")
                           for a in args) else "compile TypeScript into files"
    return None


# Programs with subcommands: the ones that only read, as "sub", "sub sub2", "* sub2" or a
# flag; "" when running it bare only reads. Option values to skip before the subcommand.
SUBCOMMANDS = {
    "docker": ({"ps", "images", "logs", "inspect", "version", "info", "stats", "top", "port", "diff", "history",
                "search", "events", "image ls", "image list", "image inspect", "image history", "container ls",
                "container list", "container inspect", "container logs", "container top", "container port",
                "container diff", "container stats", "network ls", "network inspect", "volume ls", "volume inspect",
                "context ls", "context show", "context inspect", "system df", "system info", "compose ps",
                "compose logs", "compose config", "compose ls", "compose images", "compose top", "compose version",
                "compose port", "buildx ls", "manifest inspect", ""},
               {"-H", "--host", "-c", "--context", "--config", "-l", "--log-level", "-f", "--file", "-p",
                "--project-name", "--tail", "-n", "--format"}),
    "kubectl": ({"get", "describe", "logs", "top", "version", "explain", "api-resources", "api-versions",
                 "cluster-info", "diff", "events", "config view", "config get-contexts", "config current-context",
                 "config get-clusters", "config get-users", "auth can-i", "auth whoami", "rollout status",
                 "rollout history", ""},
                {"-n", "--namespace", "--context", "--kubeconfig", "--cluster", "--user", "-l", "--selector", "-o",
                 "--output", "-c", "--container", "-f", "--filename", "--tail", "--since"}),
    "systemctl": ({"status", "show", "is-active", "is-enabled", "is-failed", "is-system-running", "list-units",
                   "list-unit-files", "list-timers", "list-sockets", "list-jobs", "list-dependencies", "cat", "help",
                   "get-default", "show-environment", "--version", ""},
                  {"-H", "--host", "-M", "--machine", "-p", "--property", "-n", "--lines", "-t", "--type", "-o",
                   "--output", "--state"}),
    "service": ({"* status", "--status-all", "list"}, set()),
    "launchctl": ({"list", "print", "print-disabled", "print-cache", "blame", "dumpstate", "managername",
                   "manageruid", "managerpid", "error", "version", "procinfo", "hostinfo", "resolveport", "examine",
                   "help", ""}, set()),
    "brew": ({"list", "ls", "info", "abv", "search", "outdated", "deps", "uses", "config", "doctor", "dr", "--prefix",
              "--cellar", "--repository", "--repo", "--version", "home", "homepage", "desc", "leaves", "commands",
              "--cache", "--env", "log", "cat", "options", "missing", "tap-info", "services list", "services info",
              "formulae", "casks", "tap", ""}, set()),
    "vercel": ({"ls", "list", "inspect", "logs", "whoami", "help", "--version", "-v", "env ls", "env list",
                "domains ls", "domains list", "domains inspect", "dns ls", "dns list", "project ls", "project list",
                "project inspect", "projects ls", "projects list", "alias ls", "alias list", "certs ls", "secrets ls",
                "teams ls", "teams list", "integration list"},
               {"--scope", "-S", "--token", "-t", "-A", "--local-config", "-Q", "--global-config", "--cwd"}),
    "supabase": ({"status", "--version", "help", "projects list", "functions list", "secrets list", "migration list",
                  "branches list", "branches get", "orgs list", "inspect *", "db lint", "storage ls", "services"},
                 {"--project-ref", "--workdir", "-o", "--output", "--profile"}),
    "swift": ({"test", "--version", "package describe", "package dump-package", "package show-dependencies",
               "package show-executables"}, set()),
    "xcodebuild": ({"-list", "-showBuildSettings", "-version", "-showsdks", "-showdestinations", "test", "-help"},
                   {"-project", "-workspace", "-scheme", "-target", "-configuration", "-destination", "-sdk",
                    "-derivedDataPath", "-resultBundlePath", "-testPlan"}),
    "xcrun": ({"simctl list", "--find", "-f", "--show-sdk-path", "--show-sdk-version", "xctrace list"},
              {"--sdk", "-sdk", "--toolchain"}),
    "pip": ({"list", "show", "freeze", "check", "search", "help", "--version", "-V", "config list", "config get",
             "config debug", "index versions", "inspect", "debug", "cache list", "cache dir"}, {"--python"}),
    "crontab": ({"-l"}, set()),
    "defaults": ({"read", "read-type", "domains", "find", "help"}, {"-host"}),
    "pmset": ({"-g"}, set()),
    "diskutil": ({"list", "info", "activity", "apfs list", "apfs listSnapshots", "listFilesystems"}, set()),
    "tmutil": ({"status", "listbackups", "latestbackup", "machinedirectory", "destinationinfo", "isexcluded",
                "listlocalsnapshots", "listlocalsnapshotdates", "version", "calculatedrift", "uniquesize",
                "compare"}, set()),
    "scutil": ({"--get", "--dns", "--proxy", "--nwi", "-r", "--version"}, set()),
    "codesign": ({"-d", "--display", "-v", "--verify", "-dv", "-dvv", "-dvvv", "-vvv", "-vv"},
                 {"--entitlements", "-r"}),
    "spctl": ({"--status", "--assess", "-a", "-s"}, set()),
    "csrutil": ({"status"}, set()),
    "mdutil": ({"-s"}, set()),
    "claude": ({"--version", "-v", "-h", "--help", "doctor", "mcp list", "mcp get", "config get", "config list",
                "plugin list", "plugins list", "plugin marketplace list"}, set()),
    "terraform": ({"plan", "validate", "show", "output", "version", "providers", "graph", "state list", "state show",
                   "workspace list", "workspace show"}, {"-chdir"}),
    "uv": ({"--version", "version", "pip list", "pip show", "pip freeze", "tree", "python list", "help"}, set()),
    "poetry": ({"show", "check", "--version", "env info", "env list", "about"}, set()),
    "ollama": ({"list", "ls", "ps", "show", "help", "--version", "-v", ""}, set()),
    "winget": ({"list", "search", "show", "--version", "--info", "source list"}, set()),
    "sc": ({"query", "queryex", "qc", "GetDisplayName", "GetKeyName"}, set()),
}
SUBCOMMANDS["pip3"] = SUBCOMMANDS["pip"]
SUBCOMMANDS["docker-compose"] = ({"ps", "logs", "config", "ls", "images", "top", "version", "port"}, set())
CLOUD = {"aws", "gcloud", "az", "doctl", "flyctl", "fly", "heroku", "netlify", "railway", "wrangler", "firebase",
         "stripe", "render", "gsutil"}


def sub_change(prog, args):
    reads, takes = SUBCOMMANDS[prog]
    pos = positional(args, takes)
    one, two = (pos[0] if pos else ""), (pos[1] if len(pos) > 1 else "")
    if (one in reads and (one != "" or not args)) or "%s %s" % (one, two) in reads or "%s *" % one in reads \
            or "* %s" % two in reads or any(a in reads for a in args if a.startswith("-")):
        return None
    if prog in ("defaults", "pip", "pip3", "crontab") and not args:
        return None
    return Unknown(("run %s %s" % (prog, one)).strip())


def cloud_change(prog, args, here, body, depth):
    reads = ("list", "ls", "describe", "get", "show", "status", "logs", "info", "whoami", "version", "inspect",
             "--version", "help")
    if any(a in reads or a.startswith(("describe-", "list-", "get-", "show-")) for a in positional(args)) or \
            any(a in ("--version", "--help") for a in args):
        return None
    return "run %s " % prog + " ".join(positional(args)[:2])


def output_change(prog, args, here, body, depth):
    """Programs that write the file they're given last."""
    pos = positional(args, {"-i", "-f", "-c:v", "-c:a", "-vf", "-af", "-r", "-s", "-b:v", "-b:a", "-t", "-ss",
                            "-to", "-map", "-T", "-R", "-l", "-o", "--out", "--setProperty"})
    if prog == "sips" and not any(a in ("-s", "--setProperty", "-o", "--out", "-r", "--rotate", "-z", "-Z", "-c",
                                        "--resampleWidth", "--resampleHeight") for a in args):
        return None
    if prog == "exiftool" and not any("=" in a or a in ("-overwrite_original", "-o") for a in args):
        return None
    if prog == "pdftotext":
        out = pos[1] if len(pos) > 1 else (re.sub(r"\.pdf$", "", pos[0], flags=re.I) + ".txt" if pos else "")
        return None if out == "-" or scratch(out, here) else "write %s" % out
    out = next((args[k + 1] for k, a in enumerate(args[:-1]) if a in ("-o", "--out")), None) or (pos[-1] if pos else "")
    return None if out in ("-", "") or scratch(out, here) else "write %s" % out


def watch_change(prog, args, here, body, depth):
    i = 0
    while i < len(args) and args[i].startswith("-"):
        i += 2 if args[i] in ("-n", "--interval", "-q", "--equexit") else 1
    return command_change(args[i:], here, body, depth) if args[i:] else None


def source_change(prog, args, here, body, depth):
    if not args or os.path.basename(args[0]) in ("activate", ".env", ".envrc", "env") or args[0].endswith(
            ("/activate", "rc", ".env")):
        return None
    return script_change(args[0], args[1:], here, depth, "shell")


def powershell_change(prog, args, here, body, depth):
    """PowerShell: the command or script it is given decides, and Holdback doesn't read
    PowerShell, so it is Unknown - held, and appealable."""
    for k, a in enumerate(args):
        low = a.lower()
        if low in ("-file", "-f") and k + 1 < len(args):
            return Unknown("run the PowerShell script %s" % os.path.basename(args[k + 1]))
        if low in ("-command", "-c", "-encodedcommand", "-e", "-ec") and k + 1 < len(args):
            return Unknown("run PowerShell: %s" % args[k + 1][:80])
    return Unknown("run %s" % prog)


def misc_change(prog, args, here, body, depth):
    if prog == "plutil":
        return None if any(a in ("-p", "-lint", "-help", "-type") for a in args) or \
            ("-extract" in args and "-o" in args and args[args.index("-o") + 1:args.index("-o") + 2] == ["-"]) \
            else "change a property list"
    if prog == "sysctl":
        return None if "-w" not in args and not any("=" in a for a in args) else "change a kernel setting"
    if prog == "networksetup":
        return None if args and args[0].startswith(("-get", "-list", "-print", "-show", "-is")) \
            else "change network settings"
    if prog == "security":
        return None if args and args[0].startswith(("find-", "dump-", "list-", "show-", "verify-", "error")) \
            else "change the keychain"
    if prog == "xattr":
        return None if not any(a in ("-w", "-d", "-c", "-s") or re.fullmatch(r"-[a-zA-Z]*[wdc][a-zA-Z]*", a)
                               for a in args) else "change file attributes"
    if prog == "reg":
        return None if args and args[0].lower() in ("query", "export", "compare") else "change the Windows registry"
    if prog == "perl":
        if any(re.fullmatch(r"-[a-zA-Z]*i\S*", a) for a in args):
            return "edit files in place"
        code = next((args[k + 1] for k, a in enumerate(args[:-1]) if re.fullmatch(r"-[a-zA-Z]*[eE]", a)), None)
        return code_change(code, PERL_WRITES) if code is not None else (
            code_change(body, PERL_WRITES) if body else "run %s" % prog)
    if prog == "ruby":
        code = next((args[k + 1] for k, a in enumerate(args[:-1]) if a == "-e"), None)
        return code_change(code, RUBY_WRITES) if code is not None else "run %s" % prog
    if prog == "eval":
        return _bash(" ".join(args), here, depth + 1)
    if prog in ("sudo", "doas"):
        return "run a command as root"
    return "run %s" % prog


HANDLERS = {
    "git": git_change, "gh": gh_change, "curl": curl_change, "wget": wget_change, "sed": sed_change, "gsed": sed_change,
    "awk": awk_change, "gawk": awk_change, "mawk": awk_change, "nawk": awk_change, "find": find_change,
    "xargs": xargs_change, "sort": sort_change, "uniq": uniq_change, "tee": tee_change, "dd": dd_change,
    "tar": tar_change, "gtar": tar_change, "bsdtar": tar_change, "unzip": unzip_change,
    "sqlite3": sqlite_change, "psql": psql_change, "mysql": psql_change, "node": node_change,
    "npm": npm_change, "pnpm": npm_change, "yarn": npm_change, "bun": npm_change,
    "npx": npx_change, "bunx": npx_change, "pnpx": npx_change, "make": make_change, "gmake": make_change,
    "cargo": cargo_change, "go": go_change, "deno": deno_change, "ssh": ssh_change, "watch": watch_change,
    "source": source_change, ".": source_change,
    "bash": shell_change, "sh": shell_change, "zsh": shell_change, "dash": shell_change, "ksh": shell_change,
    "fish": shell_change,
}
for _p in ("zip", "gzip", "gunzip", "bzip2", "bunzip2", "xz", "unxz", "zstd", "7z", "lz4", "brotli"):
    HANDLERS[_p] = packer_change
for _p in ("eslint", "prettier", "stylelint", "markdownlint", "markdownlint-cli2", "golangci-lint", "standard", "xo",
           "rubocop", "swiftlint", "ktlint", "clang-format", "shfmt", "gofmt", "autopep8", "yapf", "biome",
           "sqlfluff", "black", "isort", "ruff", "tsc", "vue-tsc"):
    HANDLERS[_p] = formatter_change
for _p in ("screencapture", "ffmpeg", "sips", "convert", "magick", "pdftotext", "exiftool"):
    HANDLERS[_p] = output_change
for _p in ("plutil", "sysctl", "networksetup", "security", "xattr", "reg", "perl", "ruby", "eval", "sudo", "doas"):
    HANDLERS[_p] = misc_change
for _p in CLOUD:
    HANDLERS[_p] = cloud_change


def unwrap(words: list) -> list:
    """The command a wrapper runs: env, nohup, timeout, nice and the like."""
    while words:
        p = os.path.basename(words[0])
        if p in ("command", "builtin", "exec", "nohup", "time", "chronic", "unbuffer", "noglob", "nocorrect"):
            words = words[1:]
            if p == "command" and words and words[0] in ("-v", "-V"):
                return []
            while words and words[0].startswith("-") and p in ("exec", "time"):
                words = words[1:]
            continue
        if p == "env":
            words = words[1:]
            while words and (words[0].startswith("-") or ASSIGN.match(words[0])):
                words = words[2:] if words[0] in ("-u", "-C", "-S", "-P", "--unset", "--chdir") else words[1:]
            continue
        if p in ("timeout", "gtimeout"):
            words = words[1:]
            while words and words[0].startswith("-"):
                words = words[2:] if words[0] in ("-s", "-k", "--signal", "--kill-after") else words[1:]
            words = words[1:]        # the duration
            continue
        if p in ("nice", "caffeinate", "stdbuf", "ionice", "taskset"):
            words = words[1:]
            while words and words[0].startswith("-"):
                words = words[2:] if words[0] in ("-n", "-t", "-w", "-c", "-p") else words[1:]
            continue
        break
    return words


# A program name on Windows may carry its extension.
WINDOWS_SUFFIXES = (".exe", ".cmd", ".bat", ".com", ".ps1")


def program_name(word: str) -> str:
    """The program a word names: its base name, without a Windows extension."""
    name = os.path.basename(word.replace("\\", "/"))
    low = name.lower()
    for suffix in WINDOWS_SUFFIXES:
        if low.endswith(suffix) and len(low) > len(suffix):
            return name[:-len(suffix)]
    return name


def command_change(words: list, here: str, body, depth: int):
    """What one simple command would change, or None when it only reads."""
    words = [w for w in words if w not in ("$", "")]
    while words and words[0] in KEYWORDS:
        words = words[1:]
    if not words or words[0] in HEADERS:
        return None
    while words and ASSIGN.match(words[0]):
        words = words[1:]
    words = unwrap(words)
    if not words:
        return None
    prog, args = program_name(words[0]), words[1:]
    if prog.startswith("-") or prog in ("]]", "]"):
        return None                  # the rest of a test expression, not a command
    if prog in HANDLERS:
        return HANDLERS[prog](prog, args, here, body, depth)
    if PYTHON.fullmatch(prog):
        return python_change(prog, args, here, body, depth)
    if prog in SUBCOMMANDS:
        return sub_change(prog, args)
    if prog in READ_PROGS:
        return None
    if prog in PATH_VERBS:
        return paths_change(prog, args, here)
    if prog in ("powershell", "pwsh"):
        return powershell_change(prog, args, here, body, depth)
    low = words[0].lower()
    if low.endswith(".py"):
        return script_change(words[0], args, here, depth, "python")
    if low.endswith((".sh", ".bash", ".zsh")):
        return script_change(words[0], args, here, depth, "shell")
    if low.endswith((".js", ".mjs", ".cjs")):
        return script_change(words[0], args, here, depth, "node")
    found = script_on_path(words[0], args, here, depth)
    return Unknown("run %s" % prog) if found is NOT_A_SCRIPT else found
