/* Voice recordings for testing (volunteers). Shows a situation; she asks it in her own words. */
(function () {
  "use strict";
  const el = LM.el, $ = (id) => document.getElementById(id);
  const K = "lm_rec_";
  const S = { list: [], i: 0, rec: null, blob: null, url: null, busy: false, msg: "", total: 0,
              who: JSON.parse(localStorage.getItem(K + "who") || "null") };
  document.documentElement.lang = "ur"; document.documentElement.dir = "rtl";

  function shuffle(a, seed) { let s = seed; const r = () => (s = (s * 9301 + 49297) % 233280) / 233280;
    for (let i = a.length - 1; i > 0; i--) { const j = Math.floor(r() * (i + 1)); [a[i], a[j]] = [a[j], a[i]]; } return a; }

  function setup() {
    const code = el("input", { class: "type-in", id: "code", placeholder: "v01", value: (S.who && S.who.speaker) || "" });
    const gender = el("select", { class: "type-in", id: "g" }, el("option", { value: "F" }, "عورت / Woman"), el("option", { value: "M" }, "مرد / Man"));
    const age = el("select", { class: "type-in", id: "a" }, ["18-30", "31-45", "46-60", "60+"].map((x) => el("option", { value: x }, x)));
    const place = el("input", { class: "type-in", id: "p", placeholder: "شہر / گاؤں · city / village" });
    const ok = el("input", { type: "checkbox", id: "ok" });
    return el("section", { class: "screen" },
      el("h1", { text: "آواز کی ریکارڈنگ (جانچ کے لیے)" }),
      el("p", { text: "آپ کو ایک صورتحال دکھائی جائے گی۔ اسے پڑھ کر نہ سنائیں — اپنے الفاظ میں ویسے پوچھیں جیسے کسی سے پوچھتیں۔ 35 سوال، تقریباً 10 منٹ۔" }),
      el("p", { class: "muted", text: "You see a situation; ask it in your OWN words, as you would ask a person. Do not say your name or real numbers." }),
      el("label", { for: "code", text: "کوڈ (نام نہیں) · Speaker code" }), code,
      el("label", { for: "g", text: "· Gender" }), gender, el("label", { for: "a", text: "عمر · Age" }), age, place,
      el("label", { class: "tips" }, ok, " میں راضی ہوں کہ میری آواز صرف اس نظام کو جانچنے کے لیے محفوظ کی جائے۔ / I agree my voice is saved only to test this system."),
      el("button", { class: "big go", type: "button", onclick: () => {
        const c = code.value.trim().replace(/[^a-zA-Z0-9_-]/g, "");
        if (!c || !ok.checked) { alert("کوڈ لکھیں اور اجازت دیں · Enter a code and tick the consent box"); return; }
        S.who = { speaker: c, gender: gender.value, age: age.value, place: place.value.trim() };
        localStorage.setItem(K + "who", JSON.stringify(S.who));
        S.i = Number(localStorage.getItem(K + "i_" + c) || 0);
        S.list = shuffle(S.all.slice(), c.split("").reduce((a, ch) => a + ch.charCodeAt(0), 7));
        render();
      } }, el("span", { class: "ico", text: "▶" }), "شروع کریں · Start"));
  }

  async function toggle() {
    if (S.rec) { S.rec.stop(); return; }
    try { S.rec = await LM.startRecording(15000); } catch (e) { S.msg = "مائیکروفون کی اجازت دیں · Allow the microphone"; render(); return; }
    render();
    S.blob = await S.rec.done; S.rec = null;
    if (S.url) URL.revokeObjectURL(S.url);
    S.url = S.blob ? URL.createObjectURL(S.blob) : null;
    render();
  }

  async function save() {
    if (!S.blob || S.busy) return;
    const sit = S.list[S.i];
    const fd = new FormData();
    const t = S.blob.type || "", ext = t.indexOf("ogg") >= 0 ? "ogg" : t.indexOf("mp4") >= 0 ? "m4a" : "webm";
    fd.append("audio", S.blob, "rec." + ext);
    fd.append("situation", sit.id); fd.append("speaker", S.who.speaker); fd.append("consent", "true");
    fd.append("gender", S.who.gender); fd.append("age", S.who.age); fd.append("place", S.who.place || "");
    S.busy = true; render();
    try {
      const r = await LM.api("/voice/collect", { method: "POST", body: fd });
      S.total = r.total; S.msg = "✓ محفوظ · saved"; next();
    } catch (e) { S.msg = (e.kind === "network" ? "کنکشن نہیں · no connection" : e.message); }
    S.busy = false; render();
  }
  function next() { S.i++; localStorage.setItem(K + "i_" + S.who.speaker, String(S.i)); S.blob = null; S.url = null; }

  function screen() {
    if (S.i >= S.list.length) return el("section", { class: "screen" }, el("h1", { text: "شکریہ! سب مکمل · All done, thank you" }),
      el("p", { text: "اگلی خاتون کے لیے نیا کوڈ لکھیں · For the next person, use a new code." }),
      el("button", { class: "big", type: "button", onclick: () => { S.who = null; localStorage.removeItem(K + "who"); render(); } }, "نیا کوڈ · New speaker"));
    const sit = S.list[S.i];
    return el("section", { class: "screen" },
      el("p", { class: "muted", text: `${S.i + 1} / ${S.list.length} · ${S.who.speaker}` }),
      el("div", { class: "panel" }, el("p", { class: "reason", text: sit.ur }), el("p", { class: "muted", text: sit.en })),
      el("p", { text: "اپنے الفاظ میں پوچھیں · Ask it in your own words" }),
      el("button", { class: "mic" + (S.rec ? " on" : ""), type: "button", onclick: toggle },
        el("span", { class: "ico", text: S.rec ? "⏹️" : "🎙️" }), S.rec ? "بس · Stop" : "بولیں · Speak"),
      S.url ? el("audio", { controls: true, src: S.url, style: "width:100%;margin:.6rem 0" }) : null,
      S.blob ? el("div", { class: "choices two" },
        el("button", { class: "choice yes", type: "button", onclick: save, disabled: S.busy }, el("span", { class: "ico", text: "✓" }), "محفوظ · Save"),
        el("button", { class: "choice no", type: "button", onclick: () => { S.blob = null; S.url = null; render(); } }, el("span", { class: "ico", text: "↺" }), "دوبارہ · Redo")) : null,
      el("button", { class: "link", type: "button", text: "چھوڑیں · Skip", onclick: () => { next(); render(); } }),
      S.msg ? el("p", { class: "flash", role: "status", text: S.msg }) : null);
  }

  function render() { $("app").replaceChildren(S.who && S.list.length ? screen() : setup()); S.msg = ""; }

  (async function () {
    const me = await LM.requireRole(["citizen", "helper", "officer", "admin", "auditor"]);
    if (!me) return;
    $("who").textContent = me.name;
    $("out-btn").addEventListener("click", LM.logout);
    S.all = await LM.api("/voice/collect/situations");
    if (S.who) { S.i = Number(localStorage.getItem(K + "i_" + S.who.speaker) || 0);
      S.list = shuffle(S.all.slice(), S.who.speaker.split("").reduce((a, ch) => a + ch.charCodeAt(0), 7)); }
    render();
  })();
})();
