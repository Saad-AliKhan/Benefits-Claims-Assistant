@echo off
rem Opens the app to phones on ANY network: a free, temporary https address (Cloudflare quick tunnel,
rem no account). Run start.bat first and leave it open (or use: start.bat phone).
rem On the phone: open the https link printed below, log in, tap "Install app". Close this window to stop.
setlocal
cd /d "%~dp0"
title Last Mile - phone link
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
echo  Open that link on the phone (Wi-Fi or mobile data). The link changes every time.
echo.
"%CF%" tunnel --url http://127.0.0.1:8080
pause
