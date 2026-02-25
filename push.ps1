# Windows용 푸시 스크립트 (push.ps1)
# 사용법: .\push.ps1

$msg = Read-Host -Prompt "커밋 메시지를 입력하세요 (엔터 시 'Self Update')"
if (-not $msg) { $msg = "Self Update" }

git add .
git commit -m $msg
git push origin main

Write-Host "`n✅ GitHub 업로드 성공! 서버에서 ./update.sh를 실행하세요." -ForegroundColor Green
