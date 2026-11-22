"""Try the whole chain on one recording, without the web service:

    python tools/voice/voice_cli.py path\\to\\question.m4a

Writes the result to last_result.json (UTF-8; open with Notepad to see the Urdu)."""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]  # project root
sys.path.insert(0, str(ROOT))
import voice_core  # noqa: E402

if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    r = voice_core.understand_bytes(Path(sys.argv[1]).read_bytes())
    Path("last_result.json").write_text(json.dumps(r, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"audio {r['seconds_audio']}s, transcribed in {r['seconds_taken']}s with '{r['model']}'")
    print(f"intent: {r['intent']}  confidence: {r['confidence']}  action: {r.get('action') or r.get('reason')}")
    print("full result: last_result.json")
