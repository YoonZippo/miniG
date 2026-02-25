# Python 3.11 슬림 이미지를 기반으로 사용 (용량이 작고 가벼움)
FROM python:3.11-slim

# 작업 디렉토리 설정
WORKDIR /app

# 시스템 의존성 패키지 업데이트 및 필요한 패키지 설치
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# 파이썬 의존성 파일 복사 및 설치
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 현재 폴더의 모든 파일을 도커 컨테이너 내부로 복사 (.dockerignore 제외)
COPY . .

# 컨테이너가 실행될 때 기본으로 실행될 명령어
CMD ["python", "miniG.py"]
