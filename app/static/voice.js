/* Voice.
   Asking:   LM.startRecording() records the question; LM.understandAudio() sends it to OUR server, which asks the
             voice service (Whisper on our machine). If that is down, LM.listen() (the browser's own speech
             recognition: Chrome/Edge, needs internet) or typing is the fallback.
   Answering: LM.speak(): server audio first (works for Urdu on any device), browser voice as the fallback. */
(function () {
  "use strict";
  const LM = (window.LM = window.LM || {});

  function browserSpeak(text, lang) {
    if (!("speechSynthesis" in window)) return;
    const ur = lang === "ur";
    speechSynthesis.cancel();
    const u = new SpeechSynthesisUtterance(text);
    u.lang = ur ? "ur-PK" : "en-US";
    u.rate = 0.9;
    const v = speechSynthesis.getVoices().find((x) => x.lang.toLowerCase().startsWith(ur ? "ur" : "en"));
    if (v) u.voice = v;
    speechSynthesis.speak(u);
  }

  let audio = null;
  async function serverSpeak(text, lang) {
    const res = await fetch("/tts?lang=" + lang + "&text=" + encodeURIComponent(text), { headers: LM.authHeaders() });
    if (!res.ok) throw new Error("tts");
    const url = URL.createObjectURL(await res.blob());
    if (audio) audio.pause();
    audio = new Audio(url);
    audio.onended = () => URL.revokeObjectURL(url);
    await audio.play();
  }

  if (typeof LM.speak !== "function") {
    LM.speak = function (text, lang) {
      serverSpeak(text, lang).catch(() => browserSpeak(text, lang)); // offline or server error: browser voice
    };
  }

  /* ---- record a question (MediaRecorder) ---- */
  const TYPES = ["audio/webm;codecs=opus", "audio/webm", "audio/ogg;codecs=opus", "audio/mp4"];
  LM.canRecord = () => !!(navigator.mediaDevices && navigator.mediaDevices.getUserMedia && window.MediaRecorder);

  /* Returns { stop(), done } where done resolves to the recorded Blob (or null). Stops by itself after maxMs. */
  LM.startRecording = async function (maxMs) {
    const stream = await navigator.mediaDevices.getUserMedia({ audio: {
      noiseSuppression: true, echoCancellation: true, autoGainControl: true, channelCount: 1 } })
      .catch(() => navigator.mediaDevices.getUserMedia({ audio: true }));
    const type = TYPES.find((t) => MediaRecorder.isTypeSupported && MediaRecorder.isTypeSupported(t)) || "";
    const rec = new MediaRecorder(stream, type ? { mimeType: type } : undefined);
    const chunks = [];
    rec.ondataavailable = (e) => { if (e.data && e.data.size) chunks.push(e.data); };
    const done = new Promise((resolve) => {
      rec.onstop = () => {
        stream.getTracks().forEach((t) => t.stop());
        resolve(chunks.length ? new Blob(chunks, { type: rec.mimeType || type || "audio/webm" }) : null);
      };
    });
    rec.start();
    const timer = setTimeout(() => { if (rec.state !== "inactive") rec.stop(); }, maxMs || 15000);
    const quiet = LM.stopOnSilence(stream, () => { if (rec.state !== "inactive") rec.stop(); });
    done.then(() => quiet.close());
    return { stop: () => { clearTimeout(timer); quiet.close(); if (rec.state !== "inactive") rec.stop(); }, done: done };
  };

  /* Stops by itself: 3 s of silence after she has spoken, or 8 s with nothing said at all. The level that counts
     as "speaking" follows the room: it is set a little above the background noise heard in the first half second. */
  LM.SILENCE_MS = 3000;
  LM.NOTHING_SAID_MS = 8000;
  LM.stopOnSilence = function (stream, onQuiet) {
    const AC = window.AudioContext || window.webkitAudioContext;
    if (!AC) return { close: () => {} };
    let ctx, closed = false, raf = 0;
    try { ctx = new AC(); } catch (e) { return { close: () => {} }; }
    const an = ctx.createAnalyser(); an.fftSize = 1024;
    ctx.createMediaStreamSource(stream).connect(an);
    const buf = new Float32Array(an.fftSize);
    const t0 = performance.now(); let floor = 0, n = 0, spoke = false, lastLoud = t0;
    const tick = () => {
      if (closed) return;
      an.getFloatTimeDomainData(buf);
      let sum = 0; for (let i = 0; i < buf.length; i++) sum += buf[i] * buf[i];
      const rms = Math.sqrt(sum / buf.length), now = performance.now();
      if (now - t0 < 500) { floor += rms; n++; }                        // learn the room's background level
      else {
        const bg = n ? floor / n : 0.005, speaking = rms > Math.max(0.015, bg * 2.5);
        if (speaking) { spoke = true; lastLoud = now; }
        if ((spoke && now - lastLoud > LM.SILENCE_MS) || (!spoke && now - t0 > LM.NOTHING_SAID_MS)) { close(); onQuiet(); return; }
      }
      raf = requestAnimationFrame(tick);
    };
    const close = () => { if (closed) return; closed = true; cancelAnimationFrame(raf); try { ctx.close(); } catch (e) { /* ignore */ } };
    if (ctx.state === "suspended" && ctx.resume) ctx.resume();
    raf = requestAnimationFrame(tick);
    return { close: close };
  };

  LM.understandAudio = function (blob) {
    const t = blob.type || "";
    const ext = t.indexOf("ogg") >= 0 ? "ogg" : t.indexOf("mp4") >= 0 ? "m4a" : "webm";
    const fd = new FormData();
    fd.append("audio", blob, "question." + ext);
    fd.append("lang", (LM.lang && LM.lang()) === "en" ? "en" : "ur");   // Whisper listens in the screen's language
    return LM.api("/voice/understand", { method: "POST", body: fd });
  };

  /* ---- browser speech recognition (fallback) ---- */
  const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
  if (typeof LM.listen !== "function" && SR) {
    LM.canListen = () => true;
    LM.listen = function (lang, onText, onEnd) {
      const r = new SR();
      r.lang = lang === "ur" ? "ur-PK" : "en-US";
      r.interimResults = false;
      r.onresult = (e) => onText(e.results[0][0].transcript);
      r.onerror = () => {};
      r.onend = onEnd;
      r.start();
      return r;
    };
  }
})();