# Holdback

A Claude Code hook. If you ask a question, Claude answers it instead of editing your code.

"Fix the login bug", "can you fix it?", a yes to something Claude offered, or a slash command all let the work through. A question, a critique, a request for a review or a plan, or a passing comment don't. Those get a hold on anything that edits, writes, commits, pushes or deploys. Claude can still read files, search, run `git log` and `git diff`, tests, linters and fetch-only `curl`, and write to the scratchpad and `/tmp`, so the answer is a real one.

I run it next to [Tether](https://github.com/bradley-t-t/tether), which checks Claude's replies before you see them.

```sh
git clone https://github.com/bradley-t-t/holdback.git ~/holdback
sh ~/holdback/install.sh
```

That adds two hooks to `~/.claude/settings.json` and leaves your other hooks alone. `--claude-md` also writes the rule into `~/.claude/CLAUDE.md`, for places that don't run hooks. Needs Python 3.9+ and a signed-in [Claude Code](https://code.claude.com) CLI. In a Claude Projects cloud thread, add the marketplace `bradley-t-t/holdback` and the `holdback` plugin under **Project settings > Plugins**. Other cloud environments can run `cloud-setup.sh` from their setup script.

## Reading your message

`UserPromptSubmit` starts judging your message in the background, so the verdict is usually ready by Claude's first tool call. The judge is a second model (`claude -p`, Opus by default). It gets your message, capped at 6,000 characters, and the last 1,500 characters of Claude's previous reply. That tail is there so "yes, do it" counts after an offer and nowhere else. It returns one kind (instruction, request, go-ahead, command, question, critique, remark and a few more) against a JSON schema. Verdicts are cached, last 40 per session. If the judge is down, a regex for instructions, polite requests and go-aheads decides.

Turns you didn't start (CI, background tasks, other sessions) go by your last real request, and so does a bare status check. A subagent goes by the turn that launched it. Headless runs are skipped unless `HOLDBACK=1`.

## Deciding what's a change

`PreToolUse` holds a call only when you didn't ask for work and the call changes something. `changes()` decides the second part:

- `Edit` and `Write` are changes, unless the path is the scratchpad or `/tmp`.
- Bash is parsed with `shlex` through pipes, `&&`, heredocs, `bash -c` and `ssh host '...'`. Known read-only commands pass. Local `.py`, `.sh` and `.js` scripts get opened and judged by what they run. Anything it doesn't recognize is a change. A wrong guess that way costs a retry. The other way costs your code.
- SQL passes only if every statement is a read, once comments and strings are stripped.
- Other MCP tools are judged by the verb in their name. `get`, `list` and `search` pass, `create`, `send` and `deploy` don't, and no verb means change.

Every hold starts with `Holdback: held` and tells Claude not to hand the task off. Tether and claude-handoff look for that marker and stay out of it.

<details>
<summary>Environment variables</summary>

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

</details>

## Trying it

```sh
python3 holdback.py classify "can you fix it?"
python3 holdback.py changes Bash '{"command": "git push"}'
python3 -m unittest discover -s tests -v
python3 holdback.py selftest   # saved messages through the real judge
```

Built with Python, using only the standard library.
