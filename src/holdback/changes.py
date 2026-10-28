"""What a tool call would change, in a few words, or None when it only reads, looks or
answers.

A tool is read by name first - the ones that only read, the servers whose tools only show
or report - and then by its input, since the same tool reads or writes depending on what it
is given: a browser click, an artifact publish, a SQL statement, a shell command. An MCP
tool Holdback has never seen is read by the verb in its name, and is a change when that
verb isn't a reading one.
"""

from __future__ import annotations

import re

from . import sql
from .paths import scratch
from .shell import bash_change

# Tools that only read, look, answer or plan.
READS = {
    "Read", "Glob", "Grep", "LS", "NotebookRead", "WebFetch", "WebSearch", "ToolSearch", "TodoWrite", "TodoRead",
    "TaskCreate", "TaskUpdate", "TaskList", "TaskGet", "TaskOutput", "TaskStop", "BashOutput", "KillShell",
    "KillBash", "Monitor", "AskUserQuestion", "EnterPlanMode", "ExitPlanMode", "Skill", "Agent", "Task",
    "Workflow", "ListAgents", "ReadNotifications", "FetchInboxMessage", "ListMcpResourcesTool",
    "ReadMcpResourceTool", "ReadMcpResourceDirTool", "ListPlugins", "ListSkills", "SearchSkills", "SearchPlugins",
    "SuggestPluginInstall", "SuggestSkills", "SendUserFile", "PushNotification", "CronList", "LSP",
    "ReportFindings", "StructuredOutput",
}
# Servers whose tools only show, plan or report: the desktop app's task list, wrap-up box,
# panes, windows and folder, inline visuals, the connector directory.
READ_SERVERS = ("mcp__ccd_turn__", "mcp__ccd_view__", "mcp__ccd_window__", "mcp__ccd_directory__",
                "mcp__visualize__", "mcp__mcp-registry__")
READ_NAMES = {"dismiss_task", "handoff_wait", "open_in_editor", "reveal_path", "request_keep_awake", "request_access",
              "request_full_control", "request_teach_access", "release_full_control", "app_release",
              "switch_display", "open_application", "app_focus", "app_bring_to_current_space", "select_browser",
              "switch_browser", "gif_creator", "javascript_tool", "preview_start", "preview_stop", "navigate",
              "resize_window", "create_session", "generate_typescript_types", "list_start_targets"}
READ_VERBS = {"get", "list", "search", "read", "query", "fetch", "find", "describe", "show", "view", "check", "count",
              "aggregate", "whoami", "export", "inspect", "lookup", "status", "preview", "explain", "validate",
              "analyze", "browse", "guide", "logs", "screenshot", "zoom", "scroll", "diff", "compare", "tabs", "wait",
              "ping", "health", "info", "help", "peek", "watch", "estimate", "summarize", "translate", "hover"}
WRITE_VERBS = {"create", "update", "delete", "remove", "add", "set", "put", "patch", "post", "send", "deploy", "apply",
               "execute", "run", "merge", "rebase", "reset", "restore", "pause", "unpause", "cancel", "approve",
               "reject", "publish", "upload", "download", "move", "rename", "copy", "write", "edit", "modify", "insert",
               "drop", "trigger", "start", "stop", "kill", "archive", "unarchive", "mark", "pin", "unpin", "assign",
               "invalidate", "issue", "buy", "purchase", "transfer", "revoke", "activate", "deactivate", "verify",
               "reply", "respond", "forward", "trash", "untrash", "batch", "import", "generate", "use", "click", "type",
               "key", "drag", "tap", "swipe", "press", "fill", "submit", "upsert", "replace", "accept", "authorize",
               "complete", "promote", "rollback", "retry", "rerun", "extend", "bind", "unbind", "sync", "clean",
               "discard", "clear", "detach", "enable", "disable", "install", "uninstall", "register", "schedule",
               "book", "order", "connect", "disconnect", "reconnect", "link", "unlink", "invite", "share", "unshare",
               "comment", "react", "like", "follow", "subscribe", "unsubscribe", "close", "save", "store", "push",
               "pull", "commit", "release", "stage", "build", "launch", "message", "handoff", "teach", "record",
               "test", "confirm", "toggle", "change", "make", "new", "init", "call", "hand", "open", "form", "menu"}
# Actions in an app that only look at what is already on screen.
LOOK_ACTIONS = {"screenshot", "zoom", "scroll", "scroll_to", "wait", "hover", "mouse_move", "cursor_position",
                "get_cursor_position", "attach", "detach", "rotate", "set_keyboard"}

EDITS = ("Edit", "Write", "MultiEdit", "NotebookEdit")
WORD = re.compile(r"[_\-]")


def changes(name: str, inp: dict, cwd: str = ""):
    """What a tool call would change, in a few words, or None when it only reads, looks or
    answers."""
    inp = inp if isinstance(inp, dict) else {}
    if name in READS or name.startswith(READ_SERVERS):
        return None
    if name in EDITS:
        path = str(inp.get("file_path") or inp.get("notebook_path") or "")
        return None if path and scratch(path, cwd) else "change %s" % (path or "a file")
    if name == "Bash" or name.endswith("__run_in_terminal"):
        return bash_change(str(inp.get("command") or ""), cwd)
    if name == "SendMessage":
        return "send another session or agent instructions"
    if name == "Artifact":
        action = inp.get("action") or "publish"
        return None if action in ("read", "list", "open", "quickstart") else "%s an artifact" % action
    if name == "ArtifactData":
        return None if inp.get("action") in ("get", "list", "query") else "change an artifact's data"
    if name == "ArtifactComments":
        return None if inp.get("action") in ("read", "list", "get", None) else "comment on an artifact"
    if not name.startswith("mcp__"):
        return "run %s" % name
    return mcp_change(name, inp, cwd)


def mcp_change(name: str, inp: dict, cwd: str):
    """What an MCP tool call would change. The tools whose input decides come first; the
    rest are read by the verb in the tool's name."""
    tool = name.rsplit("__", 1)[-1]
    if "hearthbot" in name and tool in ("reply", "post_message"):
        return None                  # a Claude Projects session answering the person
    if tool == "start_session":
        return None if inp.get("initiation") in ("offer", "own_initiative") else "start a session to do work"
    if tool == "execute_sql":
        return None if sql.reads(str(inp.get("query") or inp.get("sql") or "")) else "run SQL that changes data"
    if tool == "computer" or (tool == "control" and "Simulator" in name):
        return None if inp.get("action") in LOOK_ACTIONS else "%s in an app" % (inp.get("action") or "act")
    if tool in ("browser_batch", "computer_batch", "app_batch"):
        return batch_change(name, inp, cwd)
    if tool in READ_NAMES:
        return None
    for word in WORD.split(tool.lower()):
        if word in READ_VERBS:
            return None
        if word in WRITE_VERBS:
            break
    return "run %s" % tool


def batch_change(name: str, inp: dict, cwd: str):
    """A batch of browser, desktop or app steps: the first step that changes something."""
    server = name.rsplit("__", 1)[0]
    steps = inp.get("actions") or []
    for step in steps if isinstance(steps, list) else [None]:
        if not isinstance(step, dict):
            return "act in an app"
        if "name" in step:
            what = changes("%s__%s" % (server, step["name"]), step.get("input") or {}, cwd)
        else:
            what = None if step.get("action") in LOOK_ACTIONS else "act in an app"
        if what:
            return what
    return None
