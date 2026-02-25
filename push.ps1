# push.ps1 for Windows
# Usage: .\push.ps1

$msg = Read-Host -Prompt "Enter 'commit' (Empty for 'Self Update')"
if (-not $msg) { $msg = "Self Update" }

git add .
git commit -m $msg
git push origin main

Write-Host "`n[SUCCESS] Local changes pushed to GitHub." -ForegroundColor Green
Write-Host "Now run ./update.sh on your GCE server."
