#!/usr/bin/env bash
# push_github.sh — push the digwar_wss project to your GitHub repo.
#
# Usage:
#   cd digwar_wss
#   bash scripts/push_github.sh
#
# This script assumes you have git installed and SSH or HTTPS access to GitHub.
# It will:
#   1. Initialize a git repo in the current directory if none exists.
#   2. Add all project files.
#   3. Commit with a descriptive message.
#   4. Push to the `origin` remote (set to your repo URL below).
#
# >>> EDIT THE LINE BELOW to point to your real repo <<<
REMOTE_URL="${DIGWAR_REMOTE:-git@github.com:pipierer/digwar.git}"

set -euo pipefail

if [ ! -d ".git" ]; then
  echo "[push] initializing git repo..."
  git init -q
  git branch -M main
fi

# Set the remote (idempotent).
if ! git remote get-url origin >/dev/null 2>&1; then
  git remote add origin "$REMOTE_URL"
else
  git remote set-url origin "$REMOTE_URL"
fi

echo "[push] staging files..."
# Make sure we don't accidentally commit the zip itself if it's already in ./
git add -A

# Commit if there's anything staged.
if ! git diff --cached --quiet; then
  echo "[push] committing..."
  git commit -q -m "feat(digwar): complete authoritative WS game with strict cell-by-cell movement

- Server (Python, websockets): authoritative game logic, room/lobby, snapshots
- Client (vanilla JS): canvas renderer, HUD, minimap, FOV, interpolation
- Strict discrete movement: 1 input = 1 cell, no diagonal, no glide
- Server-side cooldowns + bounds + collision validation on every move
- Tools: shovel (dig dirt), knife (melee), bomb (chain reactions)
- Render.yaml: free-tier Web Service, Frankfurt region
- Tests: world, movement, game integration"
  echo "[push] committed."
else
  echo "[push] nothing to commit (working tree clean)."
fi

echo "[push] pushing to $REMOTE_URL (main)..."
git push -u origin main

echo "[push] done. Visit: https://github.com/pipierer/digwar"
