@echo off
rem Aasra: the whole app (claims, OCR, Urdu voice) in one program.
rem   start.bat        real OCR + Whisper (first start downloads the Whisper model, ~500 MB)
rem   start.bat mock   instant fake OCR / voice answers (for building screens)
rem   start.bat fresh  wipe the demo database and photos first (before recording / presenting the demo)
rem   start.bat phone  also opens phone.bat: a free https link so a phone (any network) can use the app
rem   Options combine:  start.bat fresh phone
rem First run creates .venv and installs packages (internet needed, a few minutes), then makes the fake
rem people, the demo accounts and some claims. Open http://127.0.0.1:8080  (demo password: demo1234)
setlocal
cd /d "%~dp0"
title Aasra - http://127.0.0.1:8080

if exist .env for /f "usebackq eol=# tokens=1,* delims==" %%a in (".env") do set "%%a=%%b"
set "FRESH=" & set "PHONE="
for %%o in (%*) do (
  if /i "%%o"=="mock" (set "OCR_MOCK=true" & set "VOICE_MOCK=true")
  if /i "%%o"=="fresh" set "FRESH=1"
  if /i "%%o"=="phone" set "PHONE=1"
)
set "HF_HUB_DISABLE_SYMLINKS_WARNING=1"

rem ---- Python 3.12 (or 3.11): the OCR engine does not install on 3.13 or newer yet
set "PY="
py -3.12 --version >nul 2>&1 && set "PY=py -3.12"
if not defined PY (py -3.11 --version >nul 2>&1 && set "PY=py -3.11")
if not defined PY (python --version 2>&1 | findstr /r /c:"Python 3\.1[12]\." >nul && set "PY=python")
if not defined PY (
  echo Python 3.12 was not found. Install it from python.org ^(tick "Add to PATH"^) and run this again.
  pause
  exit /b 1
)

if not exist .venv\Scripts\python.exe (
  echo Setting up, first run only ^(a few minutes^)...
  %PY% -m venv .venv || goto :fail
  .venv\Scripts\python.exe -m pip install -r requirements.txt || goto :fail
)
set "P=.venv\Scripts\python.exe"
if /i "%DEMO_MODE%"=="false" if defined FRESH (
  echo LIVE mode: "fresh" is ignored, real data is never wiped.
  set "FRESH="
)
if defined FRESH (
  echo Wiping the demo database and uploaded photos, and signing everyone out...
  del /q lastmile.db lastmile.db-wal lastmile.db-shm 2>nul
  if exist uploads rmdir /s /q uploads
  set "SESSION_EPOCH=%RANDOM%%RANDOM%%RANDOM%"
)
%P% -m alembic upgrade head || goto :fail
if not exist data\scenarios.json %P% -m scripts.make_fake_people || goto :fail
if not exist data\specimens\S01_cnic.jpg %P% -m tools.specimen_documents
if /i "%DEMO_MODE%"=="false" (
  rem LIVE: no fake people or claims; the first start asks for the first admin account
  %P% -m scripts.create_admin --if-none || goto :fail
) else (
  %P% -m scripts.seed --demo-claims || goto :fail
)

echo.
echo  App:       http://127.0.0.1:8080          (demo accounts on the login page, password demo1234)
echo  API docs:  http://127.0.0.1:8080/docs
echo  AI status: http://127.0.0.1:8080/health/ai
echo  Close this window to stop.
echo.
start "" http://127.0.0.1:8080/login
if defined PHONE start "Aasra - phone link" cmd /c phone.bat
%P% -m uvicorn app.main:app --host 127.0.0.1 --port 8080
pause
goto :eof

:fail
echo Something failed above. Check the internet connection and the message, then run this again.
pause
exit /b 1
