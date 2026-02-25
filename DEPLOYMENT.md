# 🚀 디스코드 봇 구글 클라우드(GCE) 배포 가이드

이 문서는 로컬에서 개발한 봇을 GitHub에 올리고, 구글 클라우드 플랫폼(GCP)의 Compute Engine VM 상에서 24시간 중단 없이 가동하는 방법을 가이드합니다.

## 1. 로컬 환경 준비 (GitHub 업로드)

이 프로젝트에는 이미 `.gitignore`가 설정되어 있어, 비공개 정보인 `.env`나 `venv` 폴더는 제외하고 코드만 올라가도록 되어 있습니다.

1.  **Git 설치**: [git-scm.com](https://git-scm.com/)에서 Git을 설치합니다. (설치 후 에디터 재시작 필요)
2.  **GitHub 리포지토리 생성**: GitHub에서 새 리포지토리(Public)를 만듭니다.
3.  **코드 푸시**: 터미널에서 다음 명령어를 순서대로 실행합니다.
    ```bash
    git init
    git add .
    git commit -m "Initial commit"
    git branch -M main
    git remote add origin https://github.com/YoonZippo/miniG.git
    git push -u origin main
    ```

## 2. 구글 클라우드(GCP) VM 생성

1.  [GCP 콘솔](https://console.cloud.google.com/) 접속 -> **Compute Engine** -> **VM 인스턴스**
2.  **인스턴스 만들기** 클릭
    -   **이름**: `discord-bot-vm`
    -   **리전**: `asia-northeast3 (서울)`
    -   **머신 유형**: `e2-micro` (기본적인 봇 구동엔 충분하며 무료 티어 대상입니다.)
    -   **부팅 디스크**: Ubuntu 최신 버전 (22.04 LTS 등)
3.  **만들기** 클릭

## 3. 서버 설정 (VM 접속 후)

VM 목록에서 **SSH** 버튼을 눌러 터미널을 켭니다.

1.  **필수 패키지 설치 (Docker & Git)**:
    ```bash
    sudo apt update && sudo apt upgrade -y
    sudo apt install -y git docker.io docker-compose
    ```
2.  **코드 가져오기**:
    ```bash
    git clone https://github.com/YoonZippo/miniG.git
    cd miniG
    ```
3.  **환경 변수 설정**:
    서버에는 `.env`가 업로드되지 않았으므로 직접 만들어줘야 합니다.
    ```bash
    nano .env
    ```
    입력 후 (우클릭 붙여넣기):
    `DISCORD_TOKEN=[여기에-나의-봇-토큰-입력]`
    (저장: `Ctrl + O`, `Enter` / 닫기: `Ctrl + X`)

## 4. 봇 구동

서버 폴더(Docker Compose가 있는 곳)에서 다음 명령어를 실행합니다.

```bash
sudo docker compose up -d --build
```

-   `-d`: 백그라운드 실행 (SSH를 꺼도 봇이 유지됩니다.)
-   `--build`: 최신 코드로 다시 빌드

## 6. 딸깍! 자동 배포 스크립트 사용법

직접 코드를 수정한 후 배포할 때, 매번 긴 명령어를 입력할 필요 없이 아래 스크립트를 사용하세요.

### 💻 로컬 PC (Windows)
1. 코드를 수정합니다.
2. 터미널(PowerShell)에서 다음을 실행합니다:
   ```powershell
   .\push.ps1
   ```
3. 커밋 메시지를 입력하면 자동으로 GitHub에 업로드됩니다.

### ☁️ 구글 VM 서버 (Linux)
1. SSH로 서버에 접속합니다.
2. 처음 한 번만 권한 설정을 해줍니다:
   ```bash
   chmod +x update.sh
   ```
3. 이제 업데이트할 때마다 다음만 입력하면 끝입니다:
   ```bash
   ./update.sh
   ```

---

## 7. (보안) 서버에서 GitHub 토큰(PAT) 제거하기

리포지토리가 퍼블릭으로 변경되었으므로, 더 이상 서버의 깃 설정에 토큰을 남겨둘 필요가 없습니다. 보안을 위해 아래 명령어를 서버에서 **딱 한 번** 실행하여 토큰이 없는 순수 주소로 변경하세요.

```bash
git remote set-url origin https://github.com/YoonZippo/miniG.git
```

이후부터는 `git pull`이나 `./update.sh` 실행 시 토큰 없이 안전하게 작동합니다.
