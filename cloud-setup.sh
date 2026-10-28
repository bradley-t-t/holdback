#!/bin/sh
# For a Claude Code cloud environment's setup script, which runs before every session in
# that environment: fetch Holdback and put its hooks in the session's ~/.claude/settings.json
# and its rule where a session that runs no hooks still reads it, so every repo opened there
# is held by the one copy here. HOLDBACK_REPO names another clone to fetch, such as your fork.
# Never fails the setup: a session without Holdback still starts, and says so in the log.
DIR="$HOME/.holdback"
REPO=${HOLDBACK_REPO:-https://github.com/bradley-t-t/holdback.git}
{
  if [ -d "$DIR/.git" ]; then git -C "$DIR" pull -q --ff-only
  else git clone -q --depth 1 "$REPO" "$DIR"; fi &&
  python3 "$DIR/holdback.py" setup --yes --claude-md
} || echo "holdback: not installed in this session" >&2
exit 0
