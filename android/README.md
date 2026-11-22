# Last Mile Android app (prototype)

The phone side of the assistant: microphone, camera, screen and speaker. The thinking (Whisper, OCR, claim
rules, database) runs on the server (for the demo: the laptop running `demo.bat`), and the app shows its
assistant screen full screen. Plain Android framework, no libraries; Android 7 and newer.

## Get the APK (free, no Android Studio)

1. Push to GitHub. The workflow `.github/workflows/android.yml` builds the app on GitHub's free machines
   (about 3-5 minutes). Or start it by hand: **Actions → Android APK → Run workflow**.
2. Open the finished run → **Artifacts → LastMile-apk** → download and unzip: `LastMile-<n>.apk`.
3. Either copy the APK to the phone, or save it as `android\LastMile.apk` in the project folder: then the
   phone can download it from `https://<your link>/app` while `demo.bat` runs.
4. On the phone, open the APK and allow "install from this source" (it is not from the Play Store).

The APK is signed with the standard debug key: fine for a demo, not for publishing.

## Opens the right server by itself

Run `tools\setup_ngrok.ps1` once (free fixed link). It writes `android/server.txt`; commit and push it, and every
APK built after that opens `https://<your-domain>.ngrok-free.app` straight away: nothing to type or paste, ever.

## Connect it to the laptop (without a built-in address)

Run `demo.bat` on the laptop. On the phone, open its `https://….trycloudflare.com` link in Chrome and tap
**📲 Open in app** (login page, or `/app`): the app opens with the server address filled in. Or type the
address on the app's first screen. The link changes each time `demo.bat` starts: tap "Open in app" again,
or ⚙️ in the app to change it.

## What is native

* Microphone and camera permissions asked by the app (works without browser https rules).
* Photo picker with the phone camera or gallery (fallback when the live camera cannot be used).
* "Connection lost, your work is saved" screen with Try again / Change server.
* Back button, full screen, its own icon; `lastmile://setup?server=…` link to set the server.
