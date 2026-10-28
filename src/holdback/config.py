"""Holdback's settings, read once into one shape.

A setting comes from its environment variable when that is set, else from config.json in
~/.config/holdback (%APPDATA%\\holdback on Windows), which `holdback setup` writes and the
hooks read, since a hook sees no shell variables. The older settings.json in the state
folder, which earlier versions wrote, is still read when config.json has nothing to say.

Everything downstream asks `settings()` and gets a Settings, so nothing elsewhere has to
wonder whether a value arrived as "0", false, a string or a list.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path

from . import system

# How long Holdback is willing to wait, and how much it shows a judge.
TIMEOUT = 75              # seconds for one verdict
APPEAL_TIMEOUT = 30       # and for an appeal, which runs after one, inside the same hook
WAIT = 80                 # how long a call waits on a verdict another process is working out
WARM_WAIT = 30            # how long the background verdict waits for the message to arrive
MESSAGE_CAP = 6000        # characters of the person's message the judge is shown
BEFORE_CAP = 1500         # and of the assistant's reply before it
KEEP = 40                 # verdicts kept per session


@dataclass
class Settings:
    """What the person chose. The defaults are the only description of each setting."""

    model: str = "opus"             # the judge model, for `claude -p`
    appeal: bool = True             # whether a command Holdback can't read may be appealed
    update: bool = True             # whether this copy keeps itself current
    allow_paths: list = field(default_factory=list)   # more places where writing changes nothing

    # Each setting's environment variable, which wins when it is set.
    VARS = {"model": "HOLDBACK_MODEL", "appeal": "HOLDBACK_APPEAL", "update": "HOLDBACK_UPDATE",
            "allow_paths": "HOLDBACK_ALLOW_PATHS"}


def config_dir() -> Path:
    return system.config_home() / "holdback"


def config_path() -> Path:
    p = os.environ.get("HOLDBACK_CONFIG")
    return Path(os.path.expanduser(p)) if p else config_dir() / "config.json"


def state_dir() -> Path:
    p = os.environ.get("HOLDBACK_STATE")
    return Path(os.path.expanduser(p)) if p else system.state_home() / "holdback"


def log_path() -> Path:
    return state_dir() / "holdback.log"


def _read(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def stored() -> dict:
    """What is in config.json, falling back to the state folder's older settings.json."""
    data = _read(config_path())
    return data if data else _read(state_dir() / "settings.json")


def write(values: dict) -> Path:
    """Keep these settings in config.json, leaving the others as they are."""
    path = config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    data = dict(_read(path), **values)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, path)
    return path


def _flag(raw) -> bool:
    return str(raw).strip().lower() not in ("0", "false", "no", "off", "")


def _paths(raw) -> list:
    if isinstance(raw, list):
        return [str(p).strip() for p in raw if str(p).strip()]
    # Comma separated, or the system's own list separator. Never ":" on Windows, where
    # it is part of C:\...
    return [p.strip() for p in str(raw).replace(os.pathsep, ",").split(",") if p.strip()]


def settings() -> Settings:
    """The settings as they stand now: the environment over the config file over the
    defaults. Read afresh each time, since a hook is a short-lived process."""
    kept, out = stored(), Settings()
    for name in ("model", "appeal", "update", "allow_paths"):
        raw = os.environ.get(Settings.VARS[name])
        if raw is None:
            raw = kept.get(name)
        if raw is None:
            continue
        if name == "allow_paths":
            out.allow_paths = _paths(raw)
        elif name == "model":
            out.model = str(raw)
        else:
            setattr(out, name, _flag(raw))
    return out
