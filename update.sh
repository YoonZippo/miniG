#!/usr/bin/env bash
# Safe fast-forward update for GCE/Linux and macOS.
# Usage: ./update.sh
set -Eeuo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

if ! git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
    echo "[ERROR] This directory is not a Git repository." >&2
    exit 1
fi

branch="$(git branch --show-current)"
if [[ "$branch" != "main" ]]; then
    echo "[ERROR] Expected branch 'main', found '$branch'. No files were changed." >&2
    exit 1
fi

if [[ -n "$(git status --porcelain --untracked-files=normal)" ]]; then
    echo "[ERROR] The working tree has local changes. Commit or back them up before updating." >&2
    git status --short
    exit 1
fi

if [[ -f database/database.db ]]; then
    backup_stamp="$(date -u +%Y%m%dT%H%M%SZ)"
    backup_path="database/database.backup-$backup_stamp.db"
    suffix=1
    while [[ -e "$backup_path" ]]; do
        backup_path="database/database.backup-$backup_stamp-$suffix.db"
        ((suffix += 1))
    done
    echo "[INFO] Backing up SQLite database to $backup_path..."
    python3 - "$SCRIPT_DIR/database/database.db" "$SCRIPT_DIR/$backup_path" <<'PY'
import sqlite3
import sys

source_path, backup_path = sys.argv[1:3]
with sqlite3.connect(source_path) as source:
    with sqlite3.connect(backup_path) as backup:
        source.backup(backup)
        result = backup.execute("PRAGMA integrity_check").fetchone()[0]
        if result != "ok":
            raise RuntimeError(f"SQLite backup integrity check failed: {result}")
PY
fi

echo "[INFO] Fetching origin/main..."
git fetch origin main
if ! git merge-base --is-ancestor HEAD origin/main; then
    echo "[ERROR] Local main cannot be fast-forwarded to origin/main. No reset or cleanup was performed." >&2
    exit 1
fi
git merge --ff-only origin/main

if docker compose version >/dev/null 2>&1; then
    compose=(docker compose)
elif sudo docker compose version >/dev/null 2>&1; then
    compose=(sudo docker compose)
else
    echo "[ERROR] Docker Compose is unavailable." >&2
    exit 1
fi

echo "[INFO] Rebuilding and restarting Docker containers..."
"${compose[@]}" up -d --build

echo "[SUCCESS] miniG bot is updated and running."
