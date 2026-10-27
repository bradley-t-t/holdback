# Holdback

Holdback keeps an AI assistant from doing work the person didn't tell it to do. Asking a question isn't telling it to work, and neither is critiquing its answer.

In a turn whose message from the person isn't an instruction to do work, Holdback refuses every tool call that would change something. Reading, searching, looking and running checks still go through, so a question gets a real answer. The session is told why, and it answers without doing the work. When the person wants the work done, they say so.

| The person's message | Holdback |
| --- | --- |
| an instruction: "fix the login bug", "make it blue", "ship it", "fix it, test it, then release it" | work goes through |
| a request phrased as a question: "can you fix the login bug?" | work goes through |
| a yes to work the assistant described: "yes", "do it", "go ahead" | work goes through |
| a slash command (`/ship`), or a plan the person approved | work goes through |
| a question: "why is the build failing?", "should we use Redis?", "is there a way to ...?" | held |
| a critique or correction: "that's wrong", "you missed the README", "the port is 8080, not 3000" | held |
| a request for an answer: explain, review, look into, propose a plan, give me options | held |
| a remark or an opinion: "I think the button should be blue" | held |
| "ok", "thanks", unless it agrees to work the assistant just offered | held |
| an instruction taken back: "fix it, actually wait, don't change anything yet" | held |

A message that mixes them counts as an instruction when any part of it tells the assistant to do work ("What does this do? Also rename it."), and a critique counts when it also says what to change ("that's wrong, change it to 8080").

### What gets held

Any call that would change something outside the conversation: an edit or a write outside the scratchpad, a shell command that writes a file, deletes, moves, installs, commits, pushes, merges, deploys, restarts or kills, a `curl` that posts, SQL that writes, a message or email sent, a page clicked or typed into, an artifact published, a session started, another session sent instructions, a check-in scheduled, a task handed off. A command Holdback doesn't know counts as a change.

What always goes through: reading files, searching, `git log` and `git diff`, `gh pr view`, `curl` that only fetches, running tests and linters, `ssh` to a host to look, the task list and wrap-up box, subagents (whose own calls are held the same way), and writing to the scratchpad, `/tmp`, Claude's own memory and plans, so the session can still write a draft and check it with Tether. Shell commands are read the way the shell reads them: quoting, pipes, `&&`, heredocs, `$(...)`, `bash -c`, `ssh host '...'`, `find -exec`, `xargs` and redirects all count, and a script run by path is read before it's judged.

### How the message is judged

A second model (`claude -p`, Opus by default) reads the person's message and the end of the assistant's reply before it, so "yes, do it" after an offer counts, and nothing else. It decides once per message, and the verdict is kept. The UserPromptSubmit hook starts that verdict in the background the moment the message is sent, so the first call that would change something rarely waits for it, and a turn that only reads never needs it. When the judge can't be reached, a word scan decides instead: an imperative sentence, a "can you ..." request or a yes to an offer is work, anything else isn't.

### Which message decides

- A person's message decides its own turn, with anything they send while it runs.
- A status check ("Status?") goes by the request it checks on.
- A turn an automated message started (CI, a background task, another session, a scheduled check-in) goes by the person's last request.
- A subagent's calls go by the turn that launched it, so a question asked while it runs doesn't stop it.
- Words Sunday relays from the person by voice count as the person's.
- A Claude Projects session goes by the person's words in its `<wake>` or coordinator relay. A thread the coordinator started has none of the person's words, and it was held at the coordinator when the coordinator started it.
- Headless runs (`claude -p`, the Agent SDK) are left alone, because routines and scripts write those prompts, unless the caller sets `HOLDBACK=1` or `TETHER=1`. `HOLDBACK_QUESTION` or `TETHER_QUESTION` then carries the person's own words.

### Beside Tether

Holdback runs beside [Tether](https://github.com/bradley-t-t/tether). Every refusal begins `Holdback: held` and says "never hand this off", so Tether never hands a held turn to another assistant, and a reply in a held turn isn't failed for stopping short of the held work or for leaving the person a step. Tether's draft check still runs: writing the draft to the scratchpad and running `tether.py check`, `hold` and `wait` always go through. `tether.py handoff` doesn't.

## Requirements

- Python 3.9 or later, standard library only.
- The [Claude Code](https://code.claude.com) CLI (`claude`), signed in. Holdback calls it as the judge.

## Install

Clone the repo once per machine and run the installer:

```sh
git clone https://github.com/bradley-t-t/holdback.git ~/holdback
sh ~/holdback/install.sh
```

`install.sh` adds Holdback's PreToolUse and UserPromptSubmit hooks to `~/.claude/settings.json`, pointing at that checkout. It replaces any older Holdback hooks and leaves the rest of the file, Tether's hooks included, as it was. Run it with `HOLDBACK_ALLOW_PATHS` set (comma separated) to add places where writing changes nothing of the person's, such as a reply drop another program reads; it keeps them in `settings.json` beside Holdback's state, so the hooks see them. With `--claude-md` it also writes the rule into `~/.claude/CLAUDE.md`, for a session that doesn't run the hooks; where they run, the UserPromptSubmit hook supplies it. To update, `git pull` the checkout.

**Claude Projects cloud threads** run the hooks of plugins added in Project settings > Plugins. This repo is a plugin and its own marketplace (`.claude-plugin/`, `hooks/hooks.json`): add the marketplace `bradley-t-t/holdback` and the `holdback` plugin there. Where install.sh's hooks are also in the user settings, the plugin's hooks step aside (`HOLDBACK_PLUGIN=1` makes them run anyway).

**Other cloud sessions**: `cloud-setup.sh`, in a cloud environment's setup script, clones Holdback and runs `install.sh --claude-md`.

## Configuration

| Variable | What it does |
| --- | --- |
| `HOLDBACK=0` | Turns Holdback off for that process. |
| `HOLDBACK=1` | Holds a headless run too, for a caller that passes a person's words to `claude -p`. `TETHER=1` does the same. |
| `HOLDBACK_QUESTION` | With `HOLDBACK=1`, the person's own words when the prompt wraps them in other instructions. `TETHER_QUESTION` does the same. |
| `HOLDBACK_MODEL` | The judge's model (default `opus`). |
| `HOLDBACK_STATE` | Where verdicts and the log are kept (default `~/.local/state/holdback`). |
| `HOLDBACK_ALLOW_PATHS` | More places, comma separated, where writing changes nothing of the person's. install.sh keeps it in `settings.json` in `HOLDBACK_STATE`; the variable, when set, wins over the file. |
| `HOLDBACK_OAUTH_TOKEN` | A token for the judge when there is no keychain sign-in, such as over SSH (else `TETHER_OAUTH_TOKEN`). Ignored when `CLAUDE_CODE_OAUTH_TOKEN` is set. |
| `HOLDBACK_PLUGIN=1` | Lets the plugin's hooks run where install.sh's hooks are also in the user settings. |

## Checking it

- `python3 holdback.py selftest` runs the person's saved messages through the judge. Every one must come out as marked.
- `python3 -m unittest discover -s tests -v` checks which shell commands and tool calls change something and which only read; which message decides a turn (a person's, one sent while it runs, a status check, an automated turn, a subagent's launch, a voice relay, a slash command, an approved plan, a Claude Projects envelope); that each message is judged once and the background verdict is used; the word scan; the hooks end to end with a stand-in judge; and that install.sh puts the hooks in beside Tether's.
- `python3 holdback.py classify "<message>" [--before "<the assistant's reply before it>"]` judges one message.
- `python3 holdback.py changes Bash '{"command": "git push"}'` says what a call would change, or `reads only`.
- Each verdict and each held call is a line in `~/.local/state/holdback/holdback.log`.
