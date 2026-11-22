@echo off
rem Opens the app to phones on ANY network (Wi-Fi or mobile data) with a free https address.
rem  - With a free ngrok account (one-time: tools\setup_ngrok.ps1): ALWAYS the same address.
rem  - Otherwise: Cloudflare quick tunnel, no account, but a NEW address every time.
rem Run start.bat first and leave it open (or use demo.bat). Close this window to stop sharing.
setlocal
cd /d "%~dp0"
title Last Mile - phone link
if exist .env for /f "usebackq eol=# tokens=1,* delims==" %%a in (".env") do if /i "%%a"=="NGROK_DOMAIN" set "NGROK_DOMAIN=%%b"

if defined NGROK_DOMAIN if exist tools\bin\ngrok.exe (
  echo.
  echo  Fixed phone link:   https://%NGROK_DOMAIN%
  echo  ^(the same every time; the Android app remembers it^)
  echo.
  tools\bin\ngrok.exe http --url=https://%NGROK_DOMAIN% 8080
  pause
  exit /b
)

set "CF=tools\bin\cloudflared.exe"
if not exist "%CF%" (
  where cloudflared >nul 2>&1 && set "CF=cloudflared"
)
if not exist "%CF%" if not "%CF%"=="cloudflared" (
  echo cloudflared.exe was not found in tools\bin.
  echo Download it ^(free^) from https://github.com/cloudflare/cloudflared/releases/latest
  echo   file: cloudflared-windows-amd64.exe  -^>  save it as tools\bin\cloudflared.exe
  pause
  exit /b 1
)
echo.
echo  Wait for a line like   https://something-random.trycloudflare.com   below.
echo  This link CHANGES every time. For a fixed link, run once:
echo      powershell -ExecutionPolicy Bypass -File tools\setup_ngrok.ps1
echo.
"%CF%" tunnel --url http://127.0.0.1:8080
pause
