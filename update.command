#!/bin/bash
# ──────────────────────────────────────────────
# miniG Mac 전용 원클릭(딸깍) 업데이트 스크립트
# Finder에서 더블 클릭하면 자동으로 최신 코드를 받고 Docker를 재시작합니다.
# ──────────────────────────────────────────────

# 1. 파일이 위치한 폴더로 이동 (Finder 더블 클릭 시 홈 디렉토리로 열리는 문제 방지)
cd "$(dirname "$0")" || exit 1

# 2. macOS 환경 변수 (Homebrew, Docker 경로 등록)
export PATH="/opt/homebrew/bin:/usr/local/bin:$HOME/.docker/bin:$PATH"

echo "==========================================="
echo "   🚀 miniG 봇 자동 업데이트 시작"
echo "==========================================="

# 3. 깃허브 최신 코드 동기화
echo -e "\n[1/3] 깃허브에서 최신 코드 가져오는 중..."
git fetch --all
git reset --hard origin/main
git clean -fd

# 4. 도커 컨테이너 재빌드 및 재시작
echo -e "\n[2/3] Docker 컨테이너 재빌드 및 재시작 중..."
if command -v docker &> /dev/null; then
    docker compose up -d --build
else
    echo "❌ Docker 명령어를 찾을 수 없습니다. Docker Desktop이 켜져 있는지 확인하세요."
    read -n 1 -s -r -p "엔터를 누르면 창이 닫힙니다..."
    exit 1
fi

# 5. 상태 확인
echo -e "\n[3/3] 실행 상태 확인..."
docker compose ps

echo -e "\n==========================================="
echo "   🎉 miniG 봇 업데이트 및 재시작 완료!"
echo "==========================================="

# 맥 화면 우측 상단 알림 띄우기
osascript -e 'display notification "miniG 봇이 최신 버전으로 업데이트되었습니다." with title "miniG 봇 업데이트 완료"' 2>/dev/null

echo -e "\n3초 후 자동으로 창이 닫힙니다 (또는 아무 키나 누르세요)..."
read -t 3 -n 1 -s -r
exit 0
