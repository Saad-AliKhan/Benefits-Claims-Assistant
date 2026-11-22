# Last Mile Claims: AI-assisted benefits and claims (prototype)

> **Prototype only. Every person, CNIC, document and payment here is fake.** The AI supports people's
> decisions: OCR and voice are not proof of identity or of death, and a refusal is never automatic.

A widow claims a benefit after her husband's death, on a cheap phone with a weak signal, in Urdu or English.
The system checks her identity, the death record and the programme rules, reads her documents, and
decides in one of three zones: **green** (it pays her at once), **yellow** (it asks for exactly the proof it
needs), **red** (a person decides, with notes that say what to check). Everything is in the audit log.

**The assistant** (`/assistant`, the citizen's home page) is the main way in: a voice-first conversation in Urdu
or English. She speaks (or taps a big icon button, or types), takes photos inside a card-shaped guide, and is
told the decision and why, aloud. It follows the designed conversation: greeting and language → what she needs →
consent → CNIC photo and "Your name is …, is that right?" → death certificate, or "No" → it finds the death in the
records itself → decision with the reason → payment and SMS → "Anything else?" (31 kinds of question). When things
go wrong: not understood → "please say it again", after 2 tries big Yes/No buttons; background noise → "can you
go somewhere quieter?" + buttons; signal drop → "connection weak, your work is saved", resumes at the same step;
an unreadable photo → "please take it again", then "I am not sure, an officer will check your case" with case notes.

## Run it

**Windows:** install **Python 3.12** from python.org (tick "Add to PATH"), then double-click **`start.bat`**.
macOS / Linux: `./start.sh`. The first run installs packages and makes the demo data (a few minutes); the
first real start also downloads the Whisper speech model (~500 MB, once). Then open <http://127.0.0.1:8080>.

`start.bat mock` starts with instant fake OCR and voice answers (no models), for building screens. `start.bat fresh` wipes the demo data first (do this before presenting). `start.bat phone` also opens `phone.bat`. Options combine: **`start.bat fresh phone`** is the demo start.

**On a phone, as an app (free):** with `start.bat` running, run **`phone.bat`** (needs `cloudflared` once:
`winget install --id Cloudflare.cloudflared`). It prints a temporary `https://….trycloudflare.com` link. Open it on
the phone, log in, and tap **📲 Install app** (Android Chrome) or Share → Add to Home Screen (iPhone). The app gets a
home-screen icon, opens full screen on the assistant, and the mic and camera work (https). The link changes each
time `phone.bat` starts, and works only while the laptop is on.
Settings: copy `.env.example` to `.env`. <http://127.0.0.1:8080/health/ai> says whether OCR and Whisper are loaded.

### Demo accounts (password `demo1234`, also one tap on the login page)

| Role | Account | Sees |
|---|---|---|
| Citizen | `rukhsana@demo.pk` | the assistant (voice conversation); her claim as plain buttons (📋); SMS inbox (📩); scam check; her permissions |
| Citizen | `saima@demo.pk` / `zubaida@demo.pk` / `kulsoom@demo.pk` | the "asked for proof", "no death record" and "second claim" cases, for the live demo |
| Helper | `helper@demo.pk` | the claims of families that allow her (Rukhsana, Zubaida) |
| Officer | `officer@demo.pk` | the queue of claims sent to a person, by priority and confidence |
| Admin | `admin@demo.pk` | the rule editor (versions), API keys, users |
| Auditor | `auditor@demo.pk` | evaluation numbers, every decision's full trace, the audit log, consent records |

Every scenario's citizen has an account too (`data/scenarios.json`, e.g. `rubina@demo.pk`). SPECIMEN photos of
each one's CNIC and death certificate are in `data/specimens/` (upload them in the claim to see the OCR work).

## The proposal, step by step: where it is

| Step | What | Where |
|---|---|---|
| 1 Foundation | Tables users, **roles**, cases, consents, rules (`rule_versions`), audit_log (+ decisions, documents, api_keys) | `app/models.py`, `migrations/` |
| | JWT login, 5 roles (citizen, helper, officer, admin, auditor) | `app/routers/auth.py`, `app/security.py` |
| | Server-side role check on every API; refusals are logged | `app/deps.py` (`require_role`) |
| | Audit log of every action: named events + a middleware that logs every change and every refusal; rows can never be edited or deleted | `app/audit.py`, `app/main.py`, `app/models.py` |
| 2 Mock services | identity (mock NADRA), records (mock CRMS death records), payment (mock bank, ledger in the DB, never pays twice), + programme list | `app/mock_services/`, HTTP in `/mock/...` |
| | 54 fake people incl. two "Rukhsana Bibi", two "Ayesha Khan", Muhammad/Mohammad, Fatima/Fatimah, missing fields, a dead claimant, a living "deceased" | `scripts/make_fake_people.py` → `data/*.json` |
| | Claim flow: consent → ID check → eligibility → decision → payment, progress saved after each step | `app/claims.py`, `app/routers/claims.py`, `app/static/citizen.js` |
| 3 AI | Decision with confidence, three zones, thresholds in the versioned rules | `app/decision_engine.py`, `app/rules.py` |
| | "I am not sure" handoff: red → officer queue with an automatic note listing what to check | `app/claims.py` (`handoff`) |
| | Explanations: one simple sentence (English + Urdu) for the citizen, the full trace for the officer and auditor | `decision_engine.py`, auditor page |
| | Voice: Urdu speech in (Whisper, on this machine) → intent (31 kinds, Urdu + Roman Urdu) → answered from her own claim; speech out | `voice_core/`, `urdu_intent/`, `app/routers/voice.py` |
| | **The assistant**: the whole claim as one spoken conversation, with the "when things go wrong" handling; one engine for the web screen now and WhatsApp later | `app/agent.py`, `app/routers/agent.py`, `app/static/assistant.js` |
| | Layered checks: registry + name match, SIM owner (mock telco), OCR, bank account holder name, then a person | `app/claims.py`, `app/mock_services/` |
| | SMS updates (mock gateway, inbox on the screen), never asking for PIN / OTP / money | `app/sms.py` |
| | Documents: CNIC + death certificate OCR with per-field confidence and flags | `ocr_core/`, `app/document_reader.py` |
| | Scam classifier: scam / safe / unsure + probability | `app/scam_classifier.py` |
| 4 Control | Consent page: see, change, withdraw; withdrawal blocks the next request (identity / records / payment / officers / helper) | `app/consent.py`, "My permissions" |
| | Rule editor: a change is a new version; the next decision records it; roll back = new version | `/admin` |
| | Officer queue sorted by priority and confidence | `/officer`, `app/routers/officer.py` |
| | Weak internet: small pages, no frameworks, saved progress, photos queued offline and sent later, cached app shell | `app/static/offline.js`, `sw.js` |
| 5 Proof | Evaluation numbers (below), shown to the auditor and in the public API | `tools/evaluate_claims.py` |
| | Tests: 157 (+ a jsdom run of the assistant screen) | `tests/` |
| | Public API with API key + Swagger | `/api/v1/...`, `/docs` |
| | Bonus: **Helper Mode** | consents `helper_access`, helper's family picker |

## Evaluation (Challenge 01)

`python -m tools.evaluate_claims` runs all 24 claim scenarios through the real flow in a throw-away database.
Each scenario has a hidden truth: should this claim be paid?

| | typed details only | with SPECIMEN photos (OCR) |
|---|---|---|
| auto-approved (paid at once) | 8 | 8 |
| asked for proof | 3 | 1 |
| sent to a person | 13 | 15 |
| genuine claims not auto-approved ("wrongly blocked") | 8 of 16 | 8 of 16 |
| claims that should not be paid but were paid automatically | **0 of 8** | **0 of 8** |

The 8 genuine claims that were not auto-approved are the deliberately hard ones: a death not yet in the records,
a death registered three years late, an amount above the automatic limit, a scam message in the claim, a name typo,
a blocked bank account, a bank account in her son's name (the holder-name check stops the payment), and either an incomplete registry record (typed only: asked for a CNIC photo; the photo
then lets it through) or one photo whose date of birth the OCR could not read (it asks for a clearer photo
instead of guessing). Each goes to a person or asks for proof, never to a wrong payment. Change a rule on /admin
and run it again to see the trade-off.

`--documents` adds the photos (about 5 s each on a laptop CPU). The numbers are on the auditor page.

## How it fits together

One program (FastAPI, SQLite by default):

```
phone browser ──JWT──► app (port 8080) ── role + consent checks on every call
                        ├─ claim flow ─► mock identity / records / payment / programme
                        ├─ AI: decision engine (zones) · name match · scam model · OCR engine · Whisper + intent
                        ├─ officer queue · rule editor · auditor views · public API (X-API-Key)
                        └─ audit_log (append-only)
```

* The OCR and Whisper engines load in the background when the app starts. Until they are ready (or if they fail),
  the claim still works: typed details are enough; a CNIC photo falls back to Tesseract if installed, otherwise
  an officer reads it; a voice question can be typed.
* Photos are kept in `uploads/` for the officer; OCR results go to the `documents` table. The audit log never
  holds field values, transcripts or photos.

## AI components (training and evaluation tools included)

| | Engine | Accuracy | Tools |
|---|---|---|---|
| OCR | `ocr_core/`: RapidOCR (PP-OCRv4) + a trained smart-CNIC field detector (`ocr_core/models/cnic_fields.onnx`) | specimen docs 100% of fields; 17 real low-res CNICs 91% of fields, 0 wrong values unflagged; 7 death certificate photos (1 real, 6 sample layouts) 63 of 63 key fields, after tuning on those same photos | `tools/ocr/evaluate.py`, `evaluate_labelled.py`, `train_cnic_detector.py` (+ `.md`) |
| Voice | Whisper `small` (faster-whisper, CPU; `WHISPER_MODEL=turbo` for large-v3-turbo) → `urdu_intent/` (555 example questions, 512 keywords, 31 intents) sound-alike correction + keyword intent + **meaning model** (multilingual MiniLM, ONNX, CPU): rescues unsure answers, and vetoes weak ones it finds unrelated | 0 wrong intents on all three test sets: practice 93%, held-out 85%, held-out 2: first run **69% with 5 wrong**, 91% / 0 wrong after the fixes it led to (no longer untouched); speech-error stress test 89% right, 2 wrong of 516; noon ghunna (ں) dropped or as ن: no wrong intents | `tools/voice/evaluate_intents.py`, `stress_test.py`, `compare_asr.py`, `/record` |
| Scam | TF-IDF + logistic regression (`app/ml_models/`) | see `/ai/scam-metrics` | `scripts/train_scam.py` |

**Free models** (one time, ~2.2 GB, from Hugging Face): `powershell -ExecutionPolicy Bypass -File tools\fetch_models.ps1`
puts the meaning model and Whisper small + large-v3-turbo in `models\` (git-ignored). Without the meaning model
everything still works (keywords only). On the test machine Whisper small took ~0.6-0.9 s per second of speech,
turbo ~1.6 s but spells Urdu clearly better; choose with real recordings (below).

**Real voices** (the biggest improvement): volunteers open **`/record`** (any demo login, also on a phone via
`phone.bat`), give a code (no names) and consent, and ask 35 situations in their own words. Recordings stay in
`data/recordings/` (git-ignored). Then `python tools/voice/compare_asr.py` compares the Whisper models on them:
right / unclear / WRONG through the same intent step, and seconds per second of speech.

Add a Whisper mistake to `urdu_intent/sound_alikes.json`, a new way of asking to `urdu_intent/intents.json`,
then run `python tools/voice/evaluate_intents.py` ("wrong intent" must stay 0).

## Tests

```
.venv\Scripts\python -m pytest              # all 157
.venv\Scripts\python -m pytest tests --ignore=tests/ai   # the app only (10 s)
```

## What is real and what is simulated

| Real (runs here) | Simulated |
|---|---|
| Login, roles, consent checks, audit log, decision engine, officer queue, rule versions, public API | NADRA, the death records system, the bank, the programme list (`app/mock_services`, fake data) |
| OCR of photos, Urdu speech recognition, intent detection, scam classifier | Payments ("MOCKPAY" references; no money moves) |
| Speech out (gTTS) needs internet; the browser's own voice is the fallback | The documents and people (SPECIMEN, invented) |

**Limits:** Urdu text on documents is not read (old green CNICs give names only in Urdu); only the Punjab death
certificate layout is tested; the CNIC detector uses Ultralytics YOLO (AGPL-3.0, review before any real use);
Urdu screen and spoken text should be checked by a native speaker (names come from the registry in English letters, so the Urdu voice reads them less well); the assistant speaks Urdu and English only (Sindhi, Punjabi, Pashto are not supported yet: it apologises and continues in Urdu); SQLite suits a demo, not many users at once.

## Folders

```
app/            the web app: routers/ (API + pages), claims.py, decision_engine.py, consent.py, mock_services/, static/, templates/
ocr_core/       OCR engine          voice_core/  Whisper wrapper          urdu_intent/  intent detector
data/           fake people, death records, scenarios, OCR mock answers, evaluation.json, specimens/
tools/          evaluate_claims.py, claim_runner.py, specimen_documents.py, ocr/ and voice/ training + evaluation
scripts/        make_fake_people.py, seed.py, train_scam.py, call_api.py
migrations/     database (alembic)        tests/   pytest (tests/ai: OCR and voice)
```
