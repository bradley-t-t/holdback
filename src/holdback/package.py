"""How this copy of Holdback was installed, the commands that reinstall or remove it, and
the PATH entry the installer adds: a line in shell startup files from install.sh, or a
folder in the Windows user PATH from install.ps1.

install.sh and install.ps1 install with pipx or uv from the main branch on GitHub; the
commands here are the same ones, so an update lands exactly where the installer put it. A
copy running from a git checkout - the plugin, or a cloud environment that cloned it -
updates with `git pull` instead.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

from . import system

REPO = "https://github.com/bradley-t-t/holdback"
BRANCH = "main"
PACKAGE_NAMES = ("claude-holdback", "holdback")

# Where pipx and uv usually live, for hooks that run with a short PATH. Folders that
# don't exist are skipped, so one list serves every system.
TOOL_DIRS = ("~/.local/bin", "~/.cargo/bin", "/opt/homebrew/bin", "/usr/local/bin",
             "~/AppData/Local/Microsoft/WinGet/Links", "~/scoop/shims")

# install.sh ends the PATH line it adds with this, so only Holdback's own line is removed.
PATH_MARK = "# added by Holdback"


def package_root() -> Path:
    """The folder that holds the holdback package (its src folder in a checkout)."""
    return Path(__file__).resolve().parent.parent


def install_command() -> str:
    """The one-line installer for this system."""
    if system.windows():
        return "irm https://taylorurl.com/holdback.ps1 | iex"
    return "curl -fsSL https://taylorurl.com/holdback | sh"


def checkout() -> Path | None:
    """The git checkout this copy runs from, or None. A plugin folder doesn't count:
    Claude Code keeps that one current itself."""
    if os.environ.get("CLAUDE_PLUGIN_ROOT"):
        return None
    root = package_root().parent
    return root if (root / ".git").exists() else None


def installer() -> str:
    """How this copy was installed: "pipx", "uv", "git", or "" when it can't tell."""
    prefix = Path(sys.prefix)
    if (prefix / "pipx_metadata.json").exists():
        return "pipx"
    if (prefix / "uv-receipt.toml").exists():
        return "uv"
    return "git" if checkout() else ""


def child_env() -> dict:
    """The environment for another `python -m holdback`: this package's folder on
    PYTHONPATH, so a copy running from a checkout can import itself."""
    env = dict(os.environ)
    root = str(package_root())
    paths = [p for p in env.get("PYTHONPATH", "").split(os.pathsep) if p]
    if root not in paths:
        paths.insert(0, root)
    env["PYTHONPATH"] = os.pathsep.join(paths)
    return env


def search_path() -> str:
    """PATH with the usual pipx and uv folders added, since pipx may need uv and git."""
    dirs = [d for d in os.environ.get("PATH", "").split(os.pathsep) if d]
    for d in TOOL_DIRS:
        d = str(Path(d).expanduser())
        if d not in dirs and Path(d).is_dir():
            dirs.append(d)
    return os.pathsep.join(dirs)


def tool(name: str) -> str:
    """The path of the pipx, uv or git program, or ""."""
    return shutil.which(name, path=search_path()) or ""


def source() -> str:
    """What the installer installs from: the git URL, or GitHub's tarball without git."""
    if tool("git"):
        return "git+%s.git@%s" % (REPO, BRANCH)
    return "%s/archive/%s.tar.gz" % (REPO, BRANCH)


def upgrade_command() -> list:
    """The command that brings this copy up to date, or [] when nothing can."""
    how = installer()
    if how == "git":
        git = tool("git")
        return [git, "-C", str(checkout()), "pull", "--quiet", "--ff-only"] if git else []
    path = tool(how) if how else ""
    if how == "pipx" and path:
        return [path, "install", "--force", source()]
    if how == "uv" and path:
        return [path, "tool", "install", "--force", "--reinstall", source()]
    return []


def removal_command() -> list:
    """The command that removes the installed holdback package, for how it was installed."""
    how = installer()
    name = Path(sys.prefix).name
    if how == "pipx":
        return ["pipx", "uninstall", name]
    if how == "uv":
        return ["uv", "tool", "uninstall", name]
    name = installed_name()
    if name:
        return [sys.executable, "-m", "pip", "uninstall", "-y", name]
    return []


def installed_name() -> str:
    """This project's distribution name in the running Python."""
    from importlib import metadata
    for name in PACKAGE_NAMES:
        try:
            eps = metadata.distribution(name).entry_points
        except Exception:  # noqa: BLE001
            continue
        if any(ep.value.startswith("holdback.") for ep in eps):
            return name
    return ""


def version_on_disk() -> str:
    """The version of the copy that would run next, which after a git pull is not this
    process's."""
    root = checkout()
    if not root:
        from . import __version__
        return __version__
    try:
        text = (root / "src" / "holdback" / "__init__.py").read_text(encoding="utf-8")
    except OSError:
        from . import __version__
        return __version__
    import re
    m = re.search(r'__version__\s*=\s*["\']([^"\']+)["\']', text)
    return m.group(1) if m else ""


def _git(root: Path, *args) -> str:
    """What `git <args>` prints in root, or "" when it can't be run."""
    git = tool("git")
    if not git:
        return ""
    try:
        p = subprocess.run([git, "-C", str(root), *args], capture_output=True, text=True, timeout=20)
    except OSError:
        return ""
    return p.stdout.strip() if p.returncode == 0 else ""


def checkout_held_back() -> str:
    """Why a checkout shouldn't be pulled, or "" when it can be: work in progress is the
    person's, and Holdback never moves it under them."""
    root = checkout()
    if root is None:
        return ""
    if not tool("git"):
        return "git isn't installed"
    if _git(root, "status", "--porcelain"):
        return "this checkout has changes of its own"
    branch = _git(root, "rev-parse", "--abbrev-ref", "HEAD")
    if branch != BRANCH:
        return "this checkout is on %s, not %s" % (branch or "no branch", BRANCH)
    return ""


def startup_files() -> list:
    """Every shell startup file install.sh may have added its PATH line to."""
    home = Path.home()
    zdot = Path(os.environ.get("ZDOTDIR") or home)
    conf = Path(os.environ.get("XDG_CONFIG_HOME") or home / ".config")
    files = [zdot / ".zshrc", home / ".zshrc", home / ".bashrc", home / ".bash_profile",
             home / ".bash_login", home / ".profile", conf / "fish" / "conf.d" / "holdback.fish"]
    return list(dict.fromkeys(files))


def remove_path_lines() -> list:
    """Take Holdback's PATH line out of the startup files, or on Windows its folder out of
    the user PATH. A file left empty that only Holdback wrote (fish's conf.d/holdback.fish)
    is deleted. Returns where it was removed from."""
    if system.windows():
        return ["your Windows user PATH"] if system.remove_user_path_entry() else []
    changed = []
    for f in startup_files():
        try:
            text = f.read_text(encoding="utf-8")
        except OSError:
            continue
        lines = text.splitlines(keepends=True)
        kept = [ln for ln in lines if not ln.rstrip().endswith(PATH_MARK)]
        if kept == lines:
            continue
        if not "".join(kept).strip() and f.name == "holdback.fish":
            f.unlink()
        else:
            f.write_text("".join(kept), encoding="utf-8")
        changed.append(str(f))
    return changed
