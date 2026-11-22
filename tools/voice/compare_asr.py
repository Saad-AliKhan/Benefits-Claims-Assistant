"""Which Whisper model understands REAL Pakistani Urdu best, on this laptop?

    python tools/voice/compare_asr.py                         # all models in models\\whisper-*
    python tools/voice/compare_asr.py --models small turbo    # by name (downloads if needed)
    python tools/voice/compare_asr.py --limit 40 --meaning off

Uses the volunteers' recordings from the /record page (data/recordings/index.jsonl). Each recording answers
a known situation, so for every model we count, through the SAME intent step the app uses:
  right    the intent (or yes / no / language / CNIC) was understood
  unclear  "please say it again" (safe: the assistant asks again, then shows buttons)
  WRONG    a different intent (the dangerous one: must stay ~0)
and how long the model takes per second of speech. Writes data/recordings/compare.json.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
REC = ROOT / "data" / "recordings"


def judge(situation: str, text: str) -> tuple[str, str]:
    """-> (outcome, what it understood)"""
    from app import agent
    from urdu_intent import detect_intent
    if situation == "_yes":
        yn = agent.yes_no(text)
        return ("right" if yn is True else "unclear" if yn is None else "WRONG"), str(yn)
    if situation == "_no":
        yn = agent.yes_no(text)
        return ("right" if yn is False else "unclear" if yn is None else "WRONG"), str(yn)
    if situation == "_lang":
        lang = agent.language(text)
        return ("right" if lang == "ur" else "unclear" if lang is None else "WRONG"), str(lang)
    if situation == "_cnic":
        return ("right" if agent.digits_cnic(text) else "unclear"), str(agent.digits_cnic(text))
    r = detect_intent(text)
    got = r["intent"]
    return ("right" if got == situation else "unclear" if got == "unclear" else "WRONG"), got + (
        " (meaning)" if r.get("method") == "meaning" else "")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--models", nargs="*", help="names (small, turbo, medium) or folders; default: models/whisper-*")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--meaning", choices=["on", "off"], default="on", help="use the meaning model if present")
    a = ap.parse_args()
    if a.meaning == "off":
        os.environ["MEANING_OFF"] = "1"
    rows = [json.loads(l) for l in (REC / "index.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()]
    if a.limit:
        rows = rows[:a.limit]
    models = a.models or [str(p) for p in sorted((ROOT / "models").glob("whisper-*")) if (p / "model.bin").is_file()]
    if not models:
        sys.exit("No models: run tools\\fetch_models.ps1 or pass --models small")
    import voice_core
    print(f"{len(rows)} recordings from {len({r['speaker'] for r in rows})} speakers; models: {models}\n")
    report = {"recordings": len(rows), "models": {}}
    for m in models:
        name = Path(m).name if Path(m).is_dir() else m
        t0 = time.time()
        voice_core.load_model(m)
        load_s = time.time() - t0
        counts, by_sit, secs_audio, secs_taken, details = Counter(), defaultdict(Counter), 0.0, 0.0, []
        for r in rows:
            audio = voice_core.decode((REC / r["file"]).read_bytes())
            stt = voice_core.transcribe(audio, model=m)
            out, got = judge(r["situation"], stt["text"])
            counts[out] += 1
            by_sit[r["situation"]][out] += 1
            secs_audio += stt["seconds_audio"]
            secs_taken += stt["seconds_taken"]
            details.append({"file": r["file"], "situation": r["situation"], "heard": stt["text"], "got": got, "outcome": out})
        n = max(1, len(rows))
        speed = secs_taken / max(secs_audio, 0.1)
        report["models"][name] = {"right_pct": round(100 * counts["right"] / n, 1), "unclear_pct": round(100 * counts["unclear"] / n, 1),
                                  "wrong_pct": round(100 * counts["WRONG"] / n, 1), "wrong": counts["WRONG"],
                                  "seconds_per_second_of_speech": round(speed, 2), "load_seconds": round(load_s, 1),
                                  "details": details}
        print(f"{name:<16} right {counts['right']:>3} ({100*counts['right']/n:4.1f}%)   unclear {counts['unclear']:>3}   "
              f"WRONG {counts['WRONG']:>3}   {speed:.2f} s per s of speech (a 4 s question ~ {4*speed:.1f} s)")
        for d in details:
            if d["outcome"] == "WRONG":
                print(f"    WRONG  {d['situation']:<22} heard: {d['heard'][:60]!r} -> {d['got']}")
    (REC / "compare.json").write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\n-> {REC / 'compare.json'}  (the 'heard' column shows Whisper's mistakes: add them to "
          "urdu_intent/sound_alikes.json; add new phrasings to urdu_intent/intents.json)")


if __name__ == "__main__":
    main()
