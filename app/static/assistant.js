/* The assistant screen: a voice-first conversation (app/agent.py does the thinking).
   She talks (big mic), taps a big icon button, or takes a photo inside a card-shaped guide. Each assistant turn
   is spoken aloud. Weak signal: "connection weak, your work is saved"; the answer is sent again when the
   signal returns, and the server ignores an answer it already applied (it checks the step). */
(function () {
  "use strict";
  const el = LM.el, $ = (id) => document.getElementById(id);
  const S = { turn: null, busy: false, rec: null, pending: null, typing: false, cam: null, retryTimer: null };
  const W = {
    ur: { weak: "کنکشن کمزور ہے، آپ کا کام محفوظ ہے۔ سگنل آتے ہی بھیج دوں گی۔", retry: "دوبارہ بھیجیں", talk: "بولیں",
          stop: "بس", listening: "سن رہی ہوں…", thinking: "سوچ رہی ہوں…", type: "لکھ کر بتائیں", send: "بھیجیں",
          snap: "تصویر لیں", hold: "کارڈ ساکت رکھیں…", pick: "گیلری سے تصویر", card: "کارڈ اس نشان کے اندر رکھیں", page: "پورا صفحہ اس نشان کے اندر", page_side: "صفحہ آڑا (لٹا کر) اس نشان کے اندر رکھیں",
          again: "دوبارہ شروع کریں", you: "آپ", photo: "📷 تصویر بھیجی", nosms: "ابھی کوئی SMS نہیں۔", play: "دوبارہ سنیں",
          novoice: "آواز ابھی دستیاب نہیں۔ بٹن دبائیں یا لکھیں۔", nomic: "مائیکروفون کی اجازت نہیں ملی۔ بٹن دبائیں یا لکھیں۔" },
    en: { weak: "Connection is weak, your work is saved. I will send it when the signal is back.", retry: "Send again",
          talk: "Speak", stop: "Done", listening: "Listening…", thinking: "Thinking…", type: "Type instead", send: "Send",
          snap: "Take photo", hold: "Hold still…", pick: "Photo from gallery", card: "Keep the card inside this frame",
          page: "Keep the whole page inside this frame", page_side: "Turn the page sideways and keep it inside this frame", again: "Start again", you: "You", photo: "📷 Photo sent",
          nosms: "No SMS yet.", play: "Listen again", novoice: "Voice is not available now. Tap a button or type.",
          nomic: "No microphone permission. Tap a button or type." },
  };
  const lang = () => (S.turn && S.turn.lang) || "ur";
  const w = (k) => W[lang()][k];

  function setLang() {
    const l = lang();
    document.documentElement.lang = l;
    document.documentElement.dir = l === "ur" ? "rtl" : "ltr";
  }

  /* ---------------- the conversation log ---------------- */
  function bubble(who, text, extra) {
    const b = el("div", { class: "bub " + who }, el("p", { text: text }), extra || null);
    $("log").append(b);
    b.scrollIntoView && b.scrollIntoView({ block: "end", behavior: "smooth" });
    return b;
  }
  function assistantSays(turn) {
    const say = turn.say || "";
    if (!say) return;
    const play = el("button", { class: "play", type: "button", "aria-label": w("play"), title: w("play"), text: "🔊",
                                onclick: () => LM.speak(say, lang()) });
    bubble("bot", say, play);
    try { LM.speak(say, lang()); } catch (e) {}
  }

  /* ---------------- talking to the server ---------------- */
  async function send(fields, files, mine) {
    if (S.busy) return;
    const fd = new FormData();
    Object.keys(fields || {}).forEach((k) => fields[k] != null && fd.append(k, fields[k]));
    Object.keys(files || {}).forEach((k) => fd.append(k, files[k][0], files[k][1]));
    if (S.turn) fd.append("state", S.turn.state); // the server ignores an answer it already applied
    if (mine) { const b = bubble("me", mine.text, mine.img || null); if (mine.voice) b.dataset.voice = "1"; }
    S.busy = true; S.pending = fd; renderAct();
    try {
      const turn = await LM.api("/agent/reply", { method: "POST", body: fd });
      S.pending = null; weak(false);
      show(turn);
    } catch (e) {
      S.busy = false;
      if (e.kind === "network") { weak(true); renderAct(); return; }
      S.pending = null;
      if (e.status === 503 && e.detail && e.detail.code === "voice_unavailable") { fallbackListen(); return; }
      if (e.status === 401) { location.replace("/login"); return; }
      bubble("bot err", (e.detail && (lang() === "ur" ? e.detail.message_ur : e.detail.message_en)) || e.message);
      renderAct();
    }
  }

  async function retry() {
    if (!S.pending || S.busy) return;
    const fd = S.pending;
    S.busy = true; renderAct();
    try {
      const turn = await LM.api("/agent/reply", { method: "POST", body: fd });
      S.pending = null; weak(false); show(turn);
    } catch (e) {
      S.busy = false;
      if (e.kind !== "network") { S.pending = null; weak(false); await resume(); return; }
      renderAct();
    }
  }

  function weak(on) {
    const p = $("weak");
    p.hidden = !on;
    p.replaceChildren(on ? w("weak") : "", on ? el("button", { class: "btn", type: "button", text: "🔁 " + w("retry"), onclick: retry }) : "");
    clearInterval(S.retryTimer);
    if (on) S.retryTimer = setInterval(() => { if (navigator.onLine) retry(); }, 6000);
  }

  function show(turn) {
    S.busy = false; S.turn = turn; S.typing = false;
    setLang();
    if (turn.heard && $("log").lastChild && $("log").lastChild.classList.contains("me") &&
        $("log").lastChild.dataset.voice === "1") $("log").lastChild.firstChild.textContent = "🎙️ " + turn.heard;
    assistantSays(turn);
    renderAct();
  }

  async function resume() {
    try { show(await LM.api("/agent")); }
    catch (e) { if (e.kind === "network") { weak(true); setTimeout(resume, 6000); } }
  }

  /* ---------------- her inputs ---------------- */
  async function talk() {
    if (S.rec) { S.rec.stop(); return; }
    if (!LM.canRecord()) { fallbackListen(); return; }
    try { S.rec = await LM.startRecording(25000); }
    catch (e) { bubble("bot err", w("nomic")); S.typing = true; renderAct(); return; }
    renderAct();
    const blob = await S.rec.done;
    S.rec = null;
    if (!blob) { renderAct(); return; }
    const t = blob.type || "";
    const ext = t.indexOf("ogg") >= 0 ? "ogg" : t.indexOf("mp4") >= 0 ? "m4a" : "webm";
    await send({}, { audio: [blob, "speech." + ext] }, { text: "🎙️ …", voice: true });
  }

  function fallbackListen() { // Whisper is down: the browser's own speech recognition, else typing
    if (typeof LM.listen === "function") {
      bubble("bot err", w("novoice"));
      LM.listen(lang(), (text) => send({ text: text }, null, { text: "🎙️ " + text }), () => {});
    } else { bubble("bot err", w("novoice")); S.typing = true; }
    renderAct();
  }

  function tap(b) { send({ choice: b.id }, null, { text: b.icon + " " + b.label }); }

  async function photo(file) {
    if (!file) return;
    stopCam();
    const small = await LM.shrink(file);
    const img = el("img", { class: "thumb", alt: "", src: URL.createObjectURL(small) });
    send({}, { photo: [small, (file.name || "photo.jpg")] }, { text: w("photo"), img: img });
  }

  /* camera with a guide frame (card shape for the CNIC, page shape for the certificate).
     Three things make the photo readable (checked on the specimen cards: a 640x480 webcam frame is always too
     small, a 1280x720 frame cropped to the frame reads the card at 0.99):
       1. ask the camera for its largest picture (up to 1920x1080) instead of the 640x480 default;
       2. take a short burst and keep the sharpest frame (hand shake, autofocus still settling);
       3. send only what is inside the frame (plus a margin), so the card fills the photo. */
  const CAM = { burst: 6, gapMs: 110, margin: 0.08 };

  function sharpness(src, sx, sy, sw, sh) {
    // variance of a Laplacian on a small grey copy of the frame area: higher = sharper
    const w = 320, h = Math.max(1, Math.round(w * sh / sw));
    const c = document.createElement("canvas"); c.width = w; c.height = h;
    const g = c.getContext("2d", { willReadFrequently: true });
    g.drawImage(src, sx, sy, sw, sh, 0, 0, w, h);
    const d = g.getImageData(0, 0, w, h).data, grey = new Float32Array(w * h);
    for (let i = 0; i < w * h; i++) grey[i] = 0.299 * d[4 * i] + 0.587 * d[4 * i + 1] + 0.114 * d[4 * i + 2];
    let n = 0, sum = 0, sq = 0;
    for (let y = 1; y < h - 1; y++) for (let x = 1; x < w - 1; x++) {
      const i = y * w + x, lap = 4 * grey[i] - grey[i - 1] - grey[i + 1] - grey[i - w] - grey[i + w];
      n++; sum += lap; sq += lap * lap;
    }
    return n ? sq / n - (sum / n) ** 2 : 0;
  }

  function frameArea(v, frame) {
    // the guide frame's position on screen, in the camera's own pixels, with a margin; whole picture if unknown
    const vr = v.getBoundingClientRect(), fr = frame.getBoundingClientRect();
    if (!vr.width || !fr.width || !v.videoWidth) return [0, 0, v.videoWidth, v.videoHeight];
    const k = v.videoWidth / vr.width, mx = fr.width * CAM.margin, my = fr.height * CAM.margin;
    const x0 = Math.max(0, (fr.left - vr.left - mx) * k), y0 = Math.max(0, (fr.top - vr.top - my) * k);
    const x1 = Math.min(v.videoWidth, (fr.right - vr.left + mx) * k), y1 = Math.min(v.videoHeight, (fr.bottom - vr.top + my) * k);
    return (x1 - x0 > 50 && y1 - y0 > 50) ? [x0, y0, x1 - x0, y1 - y0] : [0, 0, v.videoWidth, v.videoHeight];
  }

  async function startCam(box, hint) {
    if (!(navigator.mediaDevices && navigator.mediaDevices.getUserMedia)) return false;
    try {
      let stream;
      try {
        stream = await navigator.mediaDevices.getUserMedia({ audio: false, video: {
          facingMode: "environment", width: { ideal: 1920 }, height: { ideal: 1080 } } });
      } catch (e) {
        stream = await navigator.mediaDevices.getUserMedia({ video: { facingMode: "environment" }, audio: false });
      }
      const track = stream.getVideoTracks()[0];
      try { await track.applyConstraints({ advanced: [{ focusMode: "continuous" }] }); } catch (e) { /* not supported */ }
      const v = el("video", { autoplay: true, playsinline: true, muted: true });
      v.srcObject = stream;
      const frame = el("div", { class: "frame " + (hint === "certificate" ? "f-page" : "f-card") });
      const label = el("span", { text: w("snap") });
      const snap = el("button", { class: "big go", type: "button", onclick: async () => {
        if (snap.disabled || !v.videoWidth) return;
        snap.disabled = true; label.textContent = w("hold");
        try {
          const [sx, sy, sw, sh] = frameArea(v, frame);
          let best = null, bestScore = -1;
          for (let i = 0; i < CAM.burst; i++) {
            if (i) await new Promise((r) => setTimeout(r, CAM.gapMs));
            const c = document.createElement("canvas");
            c.width = Math.round(sw); c.height = Math.round(sh);
            c.getContext("2d").drawImage(v, sx, sy, sw, sh, 0, 0, c.width, c.height);
            const score = sharpness(c, 0, 0, c.width, c.height);
            if (score > bestScore) { best = c; bestScore = score; }
          }
          best.toBlob((b) => photo(new File([b], hint + ".jpg", { type: "image/jpeg" })), "image/jpeg", 0.92);
        } finally { snap.disabled = false; label.textContent = w("snap"); }
      } }, el("span", { class: "ico", text: "📸" }), label);
      const tip = el("p", { class: "muted", text: w(hint === "certificate" ? "page" : "card") });
      v.addEventListener("loadedmetadata", () => {
        // a laptop webcam is wide: an upright page would be too small to read, so it is held sideways
        // (the reader turns it upright); a phone held upright keeps the upright page frame
        if (hint === "certificate" && v.videoWidth > v.videoHeight) {
          frame.className = "frame f-page-side"; tip.textContent = w("page_side");
        }
      });
      S.cam = stream;
      box.replaceChildren(el("div", { class: "cam" }, v, frame), tip, snap);
      return true;
    } catch (e) { return false; }
  }
  function stopCam() { if (S.cam) { S.cam.getTracks().forEach((t) => t.stop()); S.cam = null; } }

  /* ---------------- the action area ---------------- */
  function renderAct() {
    const a = $("act"), turn = S.turn;
    stopCam();
    a.replaceChildren();
    if (!turn) return;
    if (S.busy) { a.append(el("p", { class: "status", text: w("thinking") })); return; }
    if (S.pending) return; // weak signal: the banner has the retry button
    if (turn.ended) {
      a.append(el("button", { class: "big go", type: "button", onclick: restart }, el("span", { class: "ico", text: "🔄" }), w("again")));
      return;
    }
    if (turn.expect === "photo") {
      const box = el("div", { class: "photo-box" });
      const pick = el("label", { class: "big ghost" }, el("span", { class: "ico", text: "🖼️" }), w("pick"),
        el("input", { type: "file", accept: "image/*", class: "sr-only",
                      onchange: (e) => photo(e.target.files[0]) }));
      a.append(box, pick);
      startCam(box, turn.photo_hint || "cnic").then((ok) => {
        if (!ok) box.replaceChildren(el("div", { class: "frame-static " + (turn.photo_hint === "certificate" ? "f-page" : "f-card") }),
                                     el("p", { class: "muted", text: w(turn.photo_hint === "certificate" ? "page" : "card") }));
      });
    }
    if (turn.buttons && turn.buttons.length) {
      const row = el("div", { class: "choices" + (turn.buttons.length === 2 ? " two" : "") });
      turn.buttons.forEach((b) => row.append(el("button", { class: "choice" + (b.id === "yes" ? " yes" : b.id === "no" ? " no" : ""),
        type: "button", onclick: () => tap(b) }, el("span", { class: "ico", text: b.icon }), el("span", { text: b.label }))));
      a.append(row);
    }
    if (turn.expect !== "photo") {
      const mic = el("button", { class: "mic" + (S.rec ? " on" : "") + (turn.expect === "tap" ? " small" : ""), type: "button",
                                 "aria-label": S.rec ? w("stop") : w("talk"), onclick: talk },
                     el("span", { class: "ico", text: S.rec ? "⏹️" : "🎙️" }), el("span", { text: S.rec ? w("listening") : w("talk") }));
      a.append(mic);
    }
    if (S.typing || turn.expect === "digits") {
      const inp = el("input", { type: "text", class: "type-in", inputmode: turn.expect === "digits" ? "numeric" : "text",
                                "aria-label": w("type"), placeholder: turn.expect === "digits" ? "35202-1234567-1" : "" });
      const go = () => { const v = inp.value.trim(); if (v) send({ text: v }, null, { text: "⌨️ " + v }); };
      inp.addEventListener("keydown", (e) => { if (e.key === "Enter") go(); });
      a.append(el("div", { class: "type-row" }, inp, el("button", { class: "btn primary", type: "button", text: w("send"), onclick: go })));
    } else {
      a.append(el("button", { class: "link", type: "button", text: "⌨️ " + w("type"), onclick: () => { S.typing = true; renderAct(); } }));
    }
  }

  async function restart() {
    $("log").replaceChildren();
    try { show(await LM.api("/agent/start", { method: "POST", body: { restart: true } })); }
    catch (e) { if (e.kind === "network") weak(true); }
  }

  async function showSms() {
    const list = $("sms-list");
    list.replaceChildren(el("p", { class: "muted", text: "…" }));
    $("sms").showModal ? $("sms").showModal() : ($("sms").open = true);
    try {
      const rows = await LM.api("/claims/messages");
      list.replaceChildren();
      if (!rows.length) list.append(el("p", { class: "muted", text: w("nosms") }));
      rows.forEach((m) => list.append(el("div", { class: "sms-row" }, el("p", { text: lang() === "ur" ? m.ur : m.en }),
        el("small", { class: "muted", text: m.phone + " · " + LM.when(m.at) }))));
    } catch (e) { list.replaceChildren(el("p", { class: "err", text: e.message })); }
  }

  async function init() {
    const me = await LM.requireRole(["citizen", "helper"]);
    if (!me) return;
    $("who").textContent = me.name;
    $("out-btn").addEventListener("click", LM.logout);
    $("new-btn").addEventListener("click", restart);
    $("sms-btn").addEventListener("click", showSms);
    if (window.LMNative) {   // inside the Android app: a way back to the server setup screen
      const gear = el("button", { type: "button", class: "link", "aria-label": "Server", title: "Server", text: "⚙️",
                                  onclick: () => window.LMNative.changeServer() });
      document.querySelector(".cz-tools").prepend(gear);
    }
    window.addEventListener("online", retry);
    await resume();
  }
  LM.assistant = { show: show, send: send, state: S }; // for tests
  init().catch((e) => bubble("bot err", e.message));
})();
