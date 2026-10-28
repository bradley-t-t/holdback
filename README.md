# Holdback

A Claude Code hook. If you ask a question, Claude answers it instead of editing your code.

Questions, critiques and "explain this" get a hold on anything that edits, writes, commits, pushes or deploys. Reading, searching and running checks still work, so the answer is a real one. When you want the change made, say so.

<details>
<summary>What it does</summary>

- Lets the work through when you give an instruction ("fix the login bug"), ask for it ("can you fix it?"), say yes to something Claude offered, or run a slash command.
- Holds changes when you ask a question, point out a mistake, ask for a review or a plan, or just make a comment.
- Always allowed: reading files, searching, `git log` and `git diff`, tests, linters, fetch-only `curl`, and writing to the scratchpad and `/tmp`.
- Reads shell commands the way the shell runs them. A command it doesn't know counts as a change.
- Works as a plugin in Claude Projects cloud threads too.

I run it next to Tether, a separate hook that checks Claude's replies before you see them.

</details>

<details>
<summary>How it works</summary>

One script, `holdback.py`, on two hooks.

- **`UserPromptSubmit`** starts judging your message in the background. By Claude's first tool call the answer is usually ready.
- **`PreToolUse`** asks two things: did you ask for work, and does this call change anything. Hold only when it's "no" and "yes".

**Judging the message.** A second model (`claude -p`, Opus by default) gets your message, capped at 6,000 characters, plus the last 1,500 characters of Claude's previous reply. It returns one kind (instruction, request, go-ahead, command, question, critique, remark and a few more) against a JSON schema. The previous reply is there so "yes, do it" counts after an offer and nowhere else. Each message is judged once and cached, last 40 per session. If the judge is down, a regex scan for instructions, polite requests and go-aheads decides.

**Which message counts.** Your message decides its own turn. Turns started by CI, background tasks or other sessions go by your last real request. So does a bare status check. A subagent goes by the turn that launched it. Headless runs are skipped unless `HOLDBACK=1`.

**What counts as a change.** `changes()` decides per call:

- `Edit` and `Write`: a change, unless the path is the scratchpad or `/tmp`.
- Bash: parsed with `shlex` through pipes, `&&`, heredocs, `bash -c` and `ssh host '...'`. Known read-only commands pass. Local `.py`, `.sh` and `.js` scripts get opened and judged by what they run. Anything unrecognized is a change. A wrong guess toward "change" costs a retry. A wrong guess the other way costs your code.
- SQL: passes only if every statement is a read, after comments and strings are stripped.
- Other MCP tools: split on `_` and `-` and judged by the verb. `get`, `list`, `search` pass. `create`, `send`, `deploy` don't. No verb means change.

Every hold starts with `Holdback: held` and tells Claude not to hand the task off. That marker is how Tether and claude-handoff know to stay out of it.

</details>

<details>
<summary>Requirements</summary>

- Python 3.9 or later (standard library only)
- The [Claude Code](https://code.claude.com) CLI, signed in

</details>

<details>
<summary>Install</summary>

```sh
git clone https://github.com/bradley-t-t/holdback.git ~/holdback
sh ~/holdback/install.sh
```

This adds Holdback's hooks to `~/.claude/settings.json` and leaves your other hooks alone. Add `--claude-md` to also write the rule into `~/.claude/CLAUDE.md` for places where Claude Code doesn't run hooks. To update, `git pull`.

For Claude Projects cloud threads, add the marketplace `bradley-t-t/holdback` and the `holdback` plugin under **Project settings > Plugins**. For other cloud environments, run `cloud-setup.sh` from the environment's setup script.

</details>

<details>
<summary>Configuration</summary>

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

<details>
<summary>Tests</summary>

```sh
python3 -m unittest discover -s tests -v
python3 holdback.py selftest   # runs saved messages through the real judge
```

To try one message, run `python3 holdback.py classify "<message>"`. To see what a tool call would change, run `python3 holdback.py changes Bash '{"command": "git push"}'`.

</details>

Built with Python, using only the standard library.
