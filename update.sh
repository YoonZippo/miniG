#!/bin/bash
# update.sh for GCE Server
# Usage: chmod +x update.sh && ./update.sh

echo "[INFO] Fetching latest code from GitHub..."
git fetch --all
git reset --hard origin/main
git clean -fd

echo "[INFO] Rebuilding and restarting Docker containers..."
if [[ "$OSTYPE" == "darwin"* ]]; then
    # macOS (Docker Desktop runs without sudo)
    docker compose up -d --build
else
    # Linux (GCE or Ubuntu server)
    if command -v docker &> /dev/null && docker compose version &> /dev/null; then
        docker compose up -d --build
    else
        sudo docker compose up -d --build
    fi
fi

echo "[SUCCESS] miniG bot is updated and running."
