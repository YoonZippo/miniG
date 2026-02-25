#!/bin/bash
# 서버 전용 업데이트 스크립트 (update.sh)
# 사용법: chmod +x update.sh && ./update.sh

echo "🔄 최신 코드를 깃허브에서 가져오는 중..."
git fetch --all
git reset --hard origin/main
git clean -fd

echo "🏗️ 도커 컨테이너 재빌드 및 구동 중..."
sudo docker compose up -d --build

echo "✅ 모든 작업이 완료되었습니다! 봇이 최신 상태로 실행 중입니다."
