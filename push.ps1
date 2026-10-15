# push.ps1 for Windows
# Usage: .\push.ps1

[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

# Git 경로 탐색 (PATH 또는 기본 설치 경로)
$gitCmd = "git"
if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
    if (Test-Path "X:\program files\Git\cmd\git.exe") {
        $gitCmd = "X:\program files\Git\cmd\git.exe"
    } elseif (Test-Path "C:\Program Files\Git\cmd\git.exe") {
        $gitCmd = "C:\Program Files\Git\cmd\git.exe"
    }
}

$msg = Read-Host -Prompt "Enter Update comment (if empty, 'Self Update')"
if (-not $msg) { $msg = "Self Update" }

& $gitCmd add .
& $gitCmd commit -m $msg
& $gitCmd push origin main

Write-Host "`n[SUCCESS] Local changes pushed to GitHub." -ForegroundColor Green
Write-Host "Now double-click 'update.command' on your Mac (or run ./update.sh)." -ForegroundColor Cyan
