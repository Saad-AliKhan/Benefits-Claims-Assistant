#!/usr/bin/env bash
# macOS / Linux: same as start.bat.   ./start.sh   or   ./start.sh mock
set -e
cd "$(dirname "$0")"
[ "$1" = "mock" ] && export OCR_MOCK=true VOICE_MOCK=true
PY=$(command -v python3.12 || command -v python3.11 || command -v python3)
[ -x .venv/bin/python ] || { "$PY" -m venv .venv && .venv/bin/python -m pip install -r requirements.txt; }
P=.venv/bin/python
$P -m alembic upgrade head
[ -f data/scenarios.json ] || $P -m scripts.make_fake_people
[ -f data/specimens/S01_cnic.jpg ] || $P -m tools.specimen_documents
$P -m scripts.seed --demo-claims
echo "App: http://127.0.0.1:8080   (password for demo accounts: demo1234)"
exec $P -m uvicorn app.main:app --host 127.0.0.1 --port 8080
