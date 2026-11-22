# One-time setup for a FIXED phone link (free ngrok account): after this, phone.bat always uses the same
# https://<your-name>.ngrok-free.app address, so the phone and the Android app never need a new link.
#   powershell -ExecutionPolicy Bypass -File tools\setup_ngrok.ps1
# Free plan limits (ngrok's): 1 GB traffic and 20,000 requests a month, one address; browsers see a
# one-time warning page (the Android app skips it). Your token is stored by ngrok in your user profile,
# not in this project.
$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"
Set-Location (Split-Path -Parent $PSScriptRoot)
New-Item -ItemType Directory -Force -Path tools\bin | Out-Null
$exe = "tools\bin\ngrok.exe"
if (-not (Test-Path $exe)) {
    Write-Host "Downloading ngrok (official, ~10 MB)..."
    $zip = "$env:TEMP\ngrok.zip"
    Invoke-WebRequest -Uri "https://bin.equinox.io/c/bNyj1mQVY4c/ngrok-v3-stable-windows-amd64.zip" -OutFile $zip -UseBasicParsing
    Expand-Archive -Path $zip -DestinationPath tools\bin -Force
    Remove-Item $zip
}
Write-Host ""
Write-Host "1. Sign up free at https://dashboard.ngrok.com/signup (email or GitHub)."
Write-Host "2. Copy your authtoken from https://dashboard.ngrok.com/get-started/your-authtoken"
$token = Read-Host "Paste the authtoken here"
& $exe config add-authtoken $token.Trim()
Write-Host ""
Write-Host "3. Open https://dashboard.ngrok.com/domains : your free domain looks like  something.ngrok-free.app"
$domain = (Read-Host "Type that domain (without https://)").Trim() -replace '^https?://', '' -replace '/.*$', ''
$envFile = ".env"
$lines = @()
if (Test-Path $envFile) { $lines = Get-Content $envFile | Where-Object { $_ -notmatch '^NGROK_DOMAIN=' } }
$lines += "NGROK_DOMAIN=$domain"
Set-Content -Path $envFile -Value $lines -Encoding ASCII
Write-Host ""
Write-Host "Done. phone.bat / demo.bat will now always use:  https://$domain"
