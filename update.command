#!/usr/bin/env bash
# macOS Finder launcher for the safe update script.
set -Eeuo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
export PATH="/opt/homebrew/bin:/usr/local/bin:$HOME/.docker/bin:$PATH"

"$SCRIPT_DIR/update.sh"
docker compose ps
osascript -e 'display notification "miniG 봇이 최신 버전으로 업데이트되었습니다." with title "miniG 봇 업데이트 완료"' 2>/dev/null || true
