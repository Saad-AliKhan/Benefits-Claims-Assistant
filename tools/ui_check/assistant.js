// Run:  start the app with OCR_MOCK=1 VOICE_MOCK=1 (python -m scripts.seed first), then
//       npm i jsdom fake-indexeddb && node tools/ui_check/assistant.js
// Drives the real /assistant page in jsdom (fake microphone + camera; the server runs with VOICE_MOCK so a
// recording "says" whatever window.__say holds).
const { JSDOM, VirtualConsole } = require("jsdom");
const fidb = require("fake-indexeddb");
const BASE = "http://127.0.0.1:8080";
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
let OFFLINE = false;

async function login(email) {
  const r = await fetch(BASE + "/auth/login", { method: "POST", headers: { "content-type": "application/json" },
    body: JSON.stringify({ email, password: "demo1234" }) });
  return r.json();
}
(async () => {
  const auth = await login("rukhsana@demo.pk");
  console.log("home after login:", auth.user.home);
  const errors = [], vc = new VirtualConsole(), spoken = [];
  vc.on("jsdomError", (e) => { const m = String(e.message || e); if (!/scrollTo|scrollIntoView|navigation|showModal/.test(m)) errors.push(m); });
  const dom = await JSDOM.fromURL(BASE + "/assistant", { runScripts: "dangerously", resources: "usable", pretendToBeVisual: true, virtualConsole: vc,
    beforeParse(w) {
      w.indexedDB = fidb.indexedDB; w.IDBKeyRange = fidb.IDBKeyRange;
      w.localStorage.setItem("lm_token", auth.access_token); w.localStorage.setItem("lm_me", JSON.stringify(auth.user));
      w.URL.createObjectURL = () => "blob:x"; w.URL.revokeObjectURL = () => {};
      w.LM = { speak: (t, l) => spoken.push(l + ":" + t) };
      w.fetch = async (u, o = {}) => {
        if (OFFLINE) throw new TypeError("Failed to fetch");
        let body = o.body;
        if (body && body.constructor && body.constructor.name === "FormData") {
          const fd = new FormData();
          for (const [k, v] of body.entries()) {
            if (typeof v === "string") fd.append(k, v);
            else { const bytes = await new Promise((res) => { const fr = new w.FileReader(); fr.onload = () => res(Buffer.from(fr.result)); fr.readAsArrayBuffer(v); });
                   fd.append(k, new Blob([bytes], { type: v.type }), v.name || "blob");
                   if (k === "audio") fd.append("mock_transcript", w.__say || ""); }
          }
          body = fd;
        }
        const r = await fetch(new URL(u, BASE), { method: o.method, headers: o.headers, body });
        const buf = Buffer.from(await r.arrayBuffer());
        return { ok: r.ok, status: r.status, statusText: r.statusText, json: async () => JSON.parse(buf.toString("utf8")), blob: async () => new w.Blob([buf]) };
      };
      w.navigator.mediaDevices = { getUserMedia: async (c) => { if (c.video) throw new Error("no camera in jsdom"); return { getTracks: () => [{ stop() {} }] }; } };
      w.MediaRecorder = class { constructor() { this.state = "inactive"; this.mimeType = "audio/webm"; }
        static isTypeSupported(t) { return t.startsWith("audio/webm"); } start() { this.state = "recording"; }
        stop() { this.state = "inactive"; this.ondataavailable({ data: new w.Blob(["x".repeat(400)], { type: "audio/webm" }) }); this.onstop(); } };
    } });
  const w = dom.window, d = w.document;
  const lastBot = () => { const b = [...d.querySelectorAll(".bub.bot")]; return b.length ? b[b.length - 1].querySelector("p").textContent : ""; };
  const nBot = () => d.querySelectorAll(".bub.bot").length;
  const waitFor = async (fn, ms = 15000) => { for (let i = 0; i < ms / 100; i++) { try { if (fn()) return true; } catch (e) {} await sleep(100); } return false; };
  const must = (ok, what) => { console.log((ok ? "ok    " : "FAILED") + " " + what); if (!ok) process.exitCode = 1; };
  const say = async (text) => {           // tap the mic, "speak", tap again
    const n = nBot(); w.__say = text;
    d.querySelector(".mic").click(); await sleep(150);
    d.querySelector(".mic").click();
    await waitFor(() => nBot() > n);
    console.log("   🎙️ " + text + "\n   🤖 " + lastBot().slice(0, 220));
  };
  const tap = async (label) => {
    const n = nBot();
    const b = [...d.querySelectorAll(".choice")].find((x) => x.textContent.includes(label));
    if (!b) { must(false, "button " + label); return; }
    b.click(); await waitFor(() => nBot() > n);
    console.log("   👆 " + label + "\n   🤖 " + lastBot().slice(0, 220));
  };
  const photo = async (name) => {
    const n = nBot();
    const inp = d.querySelector("input[type=file]");
    const f = new w.File([require("fs").readFileSync(__dirname + "/../../data/specimens/S01_cnic.jpg")], name, { type: "image/jpeg" });
    Object.defineProperty(inp, "files", { value: [f], configurable: true });
    inp.dispatchEvent(new w.Event("change"));
    await waitFor(() => nBot() > n);
    console.log("   📷 " + name + "\n   🤖 " + lastBot().slice(0, 220));
  };

  await waitFor(() => nBot() > 0);
  if (/محفوظ|saved/.test(lastBot())) { d.getElementById("new-btn").click(); await waitFor(() => /زبان/.test(lastBot())); }
  must(/کس زبان/.test(lastBot()) && d.querySelectorAll(".choice").length === 2, "1 greeting + language buttons");
  must(d.documentElement.dir === "rtl", "Urdu screen is right-to-left");
  await say("اردو");
  must(/کس کام میں مدد/.test(lastBot()), "2 asks what she needs");
  await say("میرے شوہر فوت ہو گئے ہیں");
  must(/افسوس/.test(lastBot()), "2 offers the relief payment");
  await say("بلبلبل");
  must(/دوبارہ بولیں/.test(lastBot()), "not understood: say again");
  await say("ززز");
  must(d.querySelector(".mic.small") && [...d.querySelectorAll(".choice")].length === 2, "after 2 tries: big Yes/No buttons");
  await tap("ہاں");
  must(/منع کر سکتی/.test(lastBot()), "3 consent question");
  await say("<noise>");
  must(/خاموش جگہ/.test(lastBot()), "noise: asks for a quiet place");
  await tap("ہاں");
  must(/شناختی کارڈ/.test(lastBot()) && d.querySelector(".frame-static.f-card"), "4 asks for the CNIC photo with a card guide");
  OFFLINE = true;
  await photo("cnic.jpg");
  await waitFor(() => !d.getElementById("weak").hidden);
  must(/کنکشن کمزور/.test(d.getElementById("weak").textContent), "signal drop: 'connection weak, your work is saved'");
  OFFLINE = false;
  const n = nBot();
  [...d.querySelectorAll("#weak button")][0].click();
  await waitFor(() => nBot() > n);
  must(/صحیح ہے/.test(lastBot()) && d.getElementById("weak").hidden, "resent after the signal returned: name check");
  console.log("   🤖 " + lastBot());
  await say("جی");
  must(/سرٹیفکیٹ/.test(lastBot()), "5 asks for the death certificate");
  await say("نہیں");
  must(/مل گیا/.test(lastBot()) && /اہل ہیں/.test(lastBot()) && /3 دن/.test(lastBot()) && /اور کچھ پوچھنا/.test(lastBot()), "5-7 found in records, eligible, paid, anything else");
  await say("فیصلہ کیوں ہوا");
  must(/وجہ/.test(lastBot()), "explains why");
  d.getElementById("sms-btn").click();
  await waitFor(() => d.querySelectorAll(".sms-row").length >= 2);
  must(d.querySelectorAll(".sms-row").length >= 2, "SMS inbox shows the messages");
  console.log("   📩 " + [...d.querySelectorAll(".sms-row p")].map((p) => p.textContent.slice(0, 70)).join("\n   📩 "));
  // reload the page: resumes where it was
  const dom2 = await JSDOM.fromURL(BASE + "/assistant", { runScripts: "dangerously", resources: "usable", pretendToBeVisual: true, virtualConsole: new VirtualConsole(),
    beforeParse(x) { x.localStorage.setItem("lm_token", auth.access_token); x.LM = { speak: () => {} }; x.indexedDB = fidb.indexedDB;
      x.fetch = async (u, o = {}) => { const r = await fetch(new URL(u, BASE), { method: o.method, headers: o.headers, body: o.body });
        const buf = Buffer.from(await r.arrayBuffer()); return { ok: r.ok, status: r.status, json: async () => JSON.parse(buf.toString("utf8")) }; }; } });
  const ok2 = await waitFor(() => dom2.window.document.querySelectorAll(".bub.bot").length > 0);
  must(ok2 && /محفوظ/.test(dom2.window.document.querySelector(".bub.bot p").textContent), "page reload resumes ('your work is saved')");
  await say("نہیں شکریہ");
  must(/اللہ حافظ/.test(lastBot()) && [...d.querySelectorAll(".big")].some((b) => /دوبارہ شروع/.test(b.textContent)), "goodbye + start again");
  must(spoken.length >= 10 && spoken.every((s) => s.startsWith("ur:")), "every turn spoken aloud in Urdu (" + spoken.length + ")");
  must(errors.length === 0, "no page errors " + JSON.stringify(errors.slice(0, 3)));
  process.exit(process.exitCode || 0);
})();
