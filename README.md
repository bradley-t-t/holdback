# Holdback

A Claude Code hook that stops Claude from changing things when you only asked a question. If your message is a question, a critique or a request for an explanation, Holdback blocks every tool call that would edit, write, commit, push or deploy. Claude can still read, search and run checks, so you get a real answer. When you want the work done, say so.

It's for anyone who uses Claude Code and is tired of asking "why is this broken?" and getting a pile of edits back.

## What it does

- Lets work through when you give an instruction ("fix the login bug"), ask for it ("can you fix it?"), say yes to something Claude offered, or run a slash command.
- Blocks changes when you ask a question, point out a mistake, ask for a review or a plan, or just make a remark.
- Still allows reading files, searching, `git log` and `git diff`, tests, linters, fetch-only `curl`, and writing to the scratchpad and `/tmp`.
- Reads shell commands the way the shell does (pipes, `&&`, heredocs, `bash -c`, `ssh host '...'`), and treats a command it doesn't know as a change.
- A second Claude model (Opus by default, via `claude -p`) classifies each message once. If it can't be reached, a simple word check decides.
- Works as a plugin in Claude Projects cloud threads too.

I run it alongside Tether, a separate hook that checks Claude's replies before you see them.

## Requirements

- Python 3.9 or later (standard library only)
- The [Claude Code](https://code.claude.com) CLI, signed in

## Install

```sh
git clone https://github.com/bradley-t-t/holdback.git ~/holdback
sh ~/holdback/install.sh
```

This adds Holdback's hooks to `~/.claude/settings.json` and leaves your other hooks alone. Add `--claude-md` to also write the rule into `~/.claude/CLAUDE.md` for places where Claude Code doesn't run hooks. To update, `git pull`.

For Claude Projects cloud threads, add the marketplace `bradley-t-t/holdback` and the `holdback` plugin under **Project settings > Plugins**. For other cloud environments, run `cloud-setup.sh` from the environment's setup script.

## Configuration

| Variable | What it does |
| --- | --- |
| `HOLDBACK=0` | Turns Holdback off |
| `HOLDBACK=1` | Also checks headless `claude -p` runs |
| `HOLDBACK_QUESTION` | With `HOLDBACK=1`, your own words to judge |
| `HOLDBACK_MODEL` | Judge model (default `opus`) |
| `HOLDBACK_STATE` | Where verdicts and the log go (default `~/.local/state/holdback`) |
| `HOLDBACK_ALLOW_PATHS` | Extra comma-separated paths Claude can always write to |
| `HOLDBACK_OAUTH_TOKEN` | Token for the judge when there's no keychain sign-in (SSH) |
| `HOLDBACK_PLUGIN=1` | Runs the plugin's hooks even when install.sh's are installed |

## Tests

```sh
python3 -m unittest discover -s tests -v
python3 holdback.py selftest   # runs saved messages through the real judge
```

To try one message, run `python3 holdback.py classify "<message>"`. To see what a tool call would change, run `python3 holdback.py changes Bash '{"command": "git push"}'`.

Built with Python, using only the standard library.
