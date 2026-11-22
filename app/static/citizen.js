/* Citizen screen: big buttons, few words, Urdu + English, works on a weak signal.
   The claim, step by step:  permissions -> my CNIC -> the death -> check -> result.
   Every step is saved on the server at once; photos are optional (the AI reads them) and wait on the phone
   when there is no signal. Voice: ask in Urdu (Whisper on our server; typing as the fallback).
   Helper Mode: a helper picks a family; the server allows it only while that family's permission is active. */
(function () {
  "use strict";
  const el = LM.el, api = LM.api, t = LM.t;
  const $ = (id) => document.getElementById(id);
  const newKey = () => (window.crypto && crypto.randomUUID) ? crypto.randomUUID() : Date.now() + "-" + Math.random().toString(16).slice(2);
  const DRAFT = "lm_draft_";
  const S = { me: null, claims: [], screen: "home", error: null, flash: null, busy: false, pending: 0,
              purposes: [], perms: null, file: null, previewUrl: null, listening: false, thinking: false,
              askText: "", lastReply: null, heard: null, msgText: localStorage.getItem(DRAFT + "msg") || "",
              verdict: null, family: null, families: [], helperEmail: "" };
  const GLYPH = { green: "✓", yellow: "!", red: "👤", none: "…" };
  const RELATIONS = ["Wife", "Husband", "Son", "Daughter", "Brother", "Sister", "Father", "Mother"];

  const errText = (e) => e.kind === "network" ? t("err_net") : e.status === 503 ? t("err_busy")
    : (e.status === 409 || e.status === 422) && e.message && e.message.length < 160 ? e.message : t("err_generic");
  const isHelper = () => !!S.me && S.me.role === "helper";
  const current = () => S.claims.find((c) => !["paid", "rejected", "withdrawn"].includes(c.status)) || S.claims[0] || null;
  const draft = (k, v) => (v === undefined ? localStorage.getItem(DRAFT + k) || "" : localStorage.setItem(DRAFT + k, v));

  function bigBtn(icon, text, onclick, cls, extra) {
    return el("button", Object.assign({ type: "button", class: "big " + (cls || ""), onclick: onclick }, extra || {}),
      el("span", { class: "ico", "aria-hidden": "true", text: icon }), el("span", { text: text }));
  }
  function speakBtn(text) {
    if (typeof LM.speak !== "function" || !text) return null;
    return el("button", { type: "button", class: "speak", "aria-label": t("listen"),
                          onclick: () => LM.speak(text, LM.lang() || "en") }, "🔊 " + t("listen"));
  }
  function notes(s) {
    if (S.flash) { s.append(el("p", { class: "flash", role: "status", text: S.flash })); S.flash = null; }
    if (S.error) s.append(el("p", { class: "err", role: "alert", text: S.error }));
  }
  function go(screen) { S.screen = screen; S.error = null; render(); window.scrollTo && window.scrollTo(0, 0); }

  /* ---------------- data ---------------- */
  async function loadClaims() {
    const key = "lm_claims_" + LM.getUid() + "_" + (localStorage.getItem("lm_acting") || "");
    try {
      S.claims = await api("/claims");
      localStorage.setItem(key, JSON.stringify(S.claims));
    } catch (e) {
      if (isHelper() && e.kind === "auth") { lostConsent(); return; }
      if (e.kind !== "network") throw e;
      S.claims = JSON.parse(localStorage.getItem(key) || "[]"); // offline: the last saved copy
    }
  }
  const refreshPending = async () => { S.pending = await LM.queue.count(); };
  function setClaim(c) { const i = S.claims.findIndex((x) => x.case_id === c.case_id); if (i >= 0) S.claims[i] = c; else S.claims.unshift(c); }

  /* ---------------- claim flow ---------------- */
  const STEP_SCREEN = { consent: "s_consent", identity: "s_identity", eligibility: "s_elig", decide: "s_review", proof: "s_result", done: "s_result" };
  function openClaim() { const c = current(); if (c) go(STEP_SCREEN[c.step] || "s_result"); }

  async function startClaim() {
    S.busy = true; render();
    try { setClaim(await api("/claims", { method: "POST" })); S.busy = false; go("s_consent"); }
    catch (e) { S.busy = false; S.error = errText(e); render(); }
  }

  async function submit(fn, nextScreen) {
    if (S.busy) return;
    S.busy = true; S.error = null; render();
    try { const c = await fn(); setClaim(c); S.busy = false; go(nextScreen || STEP_SCREEN[c.step]); }
    catch (e) { S.busy = false; S.error = errText(e); render(); }
  }

  function pickFile(f) {
    if (S.previewUrl) URL.revokeObjectURL(S.previewUrl);
    S.file = f || null; S.previewUrl = f ? URL.createObjectURL(f) : null; S.error = null; render();
  }

  /* identity / eligibility: typed fields + optional photo. No signal -> keep it on the phone, send later. */
  async function sendStep(step, fields) {
    const c = current();
    if (!c || S.busy) return;
    S.busy = true; S.error = null; render();
    const item = { key: newKey(), caseId: c.case_id, step: step, fields: fields, blob: null, name: null };
    if (S.file) {
      item.name = S.file.name || "photo.jpg";
      try { item.blob = await LM.shrink(S.file); } catch (e) { item.blob = S.file; }
    }
    try {
      const res = await LM.postStep(item);
      pickFile(null); setClaim(res); S.busy = false; go(STEP_SCREEN[res.step]);
    } catch (e) {
      S.busy = false;
      if (e.kind === "network") {
        try { await LM.queue.add(item); pickFile(null); await refreshPending(); S.flash = t("saved_offline"); go("home"); return; }
        catch (e2) {}
      }
      S.error = errText(e); render();
    }
  }

  function photoPicker(label) {
    const input = el("input", { type: "file", accept: "image/*", id: "file", class: "sr-only",
                                onchange: (e) => pickFile(e.target.files[0]) });
    const box = el("div", { class: "photo-box" }, el("p", { class: "muted", text: label }), input,
      el("label", { for: "file", class: "big ghost" }, el("span", { class: "ico", "aria-hidden": "true", text: "📷" }),
        el("span", { text: S.file ? t("retake") : t("take_photo") })));
    if (S.previewUrl) box.append(el("img", { class: "preview", src: S.previewUrl, alt: "" }));
    return box;
  }

  function stepHead(n, title) {
    return [el("p", { class: "steps", text: t("step_n", { n: n }) }), el("h1", { text: title })];
  }

  function screenConsent() {
    const chosen = new Set(S.purposes.map((p) => p.purpose));
    const s = el("section", { class: "screen" }, ...stepHead(1, t("consent_title")),
      el("p", { text: t("consent_intro") }));
    S.purposes.forEach((p) => {
      const box = el("input", { type: "checkbox", id: "p_" + p.purpose, checked: true,
                                onchange: (e) => (e.target.checked ? chosen.add(p.purpose) : chosen.delete(p.purpose)) });
      s.append(el("label", { class: "perm", for: "p_" + p.purpose }, box,
        el("span", { text: LM.lang() === "ur" ? p.ur : p.en })));
    });
    notes(s);
    s.append(bigBtn("✓", S.busy ? t("sending") : t("agree"), () => submit(() =>
      api("/claims/" + current().case_id + "/consent", { method: "POST", body: { purposes: [...chosen] } })),
      "go", S.busy ? { disabled: true } : {}));
    s.append(el("p", { class: "muted", text: t("consent_change_later") }));
    s.append(bigBtn("←", t("back"), () => go("home"), "ghost"));
    return s;
  }

  function screenIdentity() {
    const known = S.me.cnic || (isHelper() && S.family && S.family.cnic) || "";
    const cnic = el("input", { id: "cnic", inputmode: "numeric", placeholder: "35202-1234567-1", value: known || draft("cnic"),
                               readonly: !!known, "aria-label": t("your_cnic"), oninput: (e) => draft("cnic", e.target.value) });
    const s = el("section", { class: "screen" }, ...stepHead(2, t("id_title")),
      el("label", { for: "cnic", class: "fld", text: t("your_cnic") }), cnic,
      photoPicker(t("id_photo_optional")));
    notes(s);
    s.append(bigBtn("➤", S.busy ? t("checking") : t("check_continue"), () => sendStep("identity", { cnic: cnic.value.trim() }),
                    "go", S.busy ? { disabled: true } : {}));
    s.append(bigBtn("←", t("back"), () => go("home"), "ghost"));
    return s;
  }

  function screenElig() {
    const dc = el("input", { id: "dcnic", inputmode: "numeric", placeholder: "35202-7654321-1", value: draft("dcnic"),
                             "aria-label": t("deceased_cnic"), oninput: (e) => draft("dcnic", e.target.value) });
    const rel = el("select", { id: "rel", "aria-label": t("relation"), onchange: (e) => draft("rel", e.target.value) },
      RELATIONS.map((r) => el("option", { value: r, text: t("rel_" + r.toLowerCase()), selected: draft("rel") === r })));
    const s = el("section", { class: "screen" }, ...stepHead(3, t("elig_title")),
      el("label", { for: "dcnic", class: "fld", text: t("deceased_cnic") }), dc,
      el("label", { for: "rel", class: "fld", text: t("relation") }), rel,
      photoPicker(t("cert_photo_optional")));
    notes(s);
    s.append(bigBtn("➤", S.busy ? t("checking") : t("check_continue"), () =>
      sendStep("eligibility", { deceased_cnic: dc.value.trim(), relation: rel.value }), "go", S.busy ? { disabled: true } : {}));
    s.append(bigBtn("←", t("back"), () => go("s_identity"), "ghost"));
    return s;
  }

  function okLine(label, action) {
    const ok = action === "auto", g = ok ? "✓" : action === "ask_more" ? "!" : "👤";
    return el("li", { class: ok ? "ok" : "warn" }, el("span", { text: g + " " + label }));
  }

  function screenReview() {
    const c = current();
    const msg = el("textarea", { id: "smsg", rows: "3", placeholder: t("scam_optional"), "aria-label": t("scam_optional"),
                                 oninput: (e) => draft("smsg", e.target.value) });
    msg.value = draft("smsg");
    const s = el("section", { class: "screen" }, ...stepHead(4, t("review_title")),
      el("ul", { class: "checks" }, okLine(t("chk_identity"), c.identity_ok), okLine(t("chk_elig"), c.eligibility_ok)),
      el("p", { class: "amount", text: t("amount_is", { n: LM.fmt(c.amount) }) }),
      el("label", { for: "smsg", class: "fld", text: t("scam_optional") }), msg);
    notes(s);
    s.append(bigBtn("✓", S.busy ? t("sending") : t("submit_claim"), () => submit(() =>
      api("/claims/" + c.case_id + "/decide", { method: "POST", body: { message: msg.value.trim() || null },
                                                headers: { "Idempotency-Key": newKey() } })).then(() => draft("smsg", "")),
      "go", S.busy ? { disabled: true } : {}));
    s.append(bigBtn("←", t("back"), () => go("s_elig"), "ghost"));
    return s;
  }

  function decisionPanel(c) {
    const d = c && c.decision, ur = LM.lang() === "ur";
    let o = d ? d.outcome : "none", reason, next;
    if (!c) { reason = t("no_claims"); next = ""; }
    else if (c.status === "paid") { o = "green"; reason = t("paid_msg", { n: LM.fmt(c.amount) }); next = t("paid_ref", { ref: c.payment_ref }); }
    else if (c.status === "payment_failed") { o = "red"; reason = t("pay_failed"); next = t("next_red"); }
    else if (c.status === "rejected") { o = "red"; reason = t("rejected"); next = ""; }
    else if (c.status === "withdrawn") { o = "none"; reason = t("withdrawn"); next = ""; }
    else if (c.status === "draft") { reason = t("continue_step", { step: t("stepname_" + c.step) }); next = ""; }
    else if (d) { reason = ur ? d.reason_ur : d.reason; next = t("next_" + d.outcome); }
    else { reason = t("st_" + c.status); next = ""; }
    return el("div", { class: "panel " + o, role: "status" },
      el("div", { class: "light " + o, "aria-hidden": "true", text: GLYPH[o] || "…" }),
      el("p", { class: "reason", text: reason }), next ? el("p", { class: "next", text: next }) : null, speakBtn(reason));
  }

  function screenResult() {
    const c = current();
    const s = el("section", { class: "screen" }, el("h1", { text: t("result_title") }), decisionPanel(c));
    notes(s);
    if (c && c.step === "proof") {
      const asks = (c.decision && c.decision.asks_for) || [];
      if (asks.some((a) => /^id_|^doc_/.test(a)) || !asks.length) s.append(bigBtn("📷", t("send_cnic_photo"), () => { pickFile(null); go("s_identity"); }, "primary"));
      if (asks.some((a) => /^record|^death_/.test(a)) || !asks.length) s.append(bigBtn("📄", t("send_cert_photo"), () => { pickFile(null); go("s_elig"); }, "primary"));
      s.append(bigBtn("🙋", t("ask_person"), () => askOfficer("handoff").then((r) => { S.flash = r; render(); }), "ghost"));
    }
    s.append(bigBtn("🏠", t("home"), () => go("home"), "ghost"));
    return s;
  }

  async function askOfficer(kind) {
    const c = current();
    if (!c) return t("officer_no_case");
    setClaim(await api("/claims/" + c.case_id + "/ask-officer", { method: "POST", body: { kind: kind } }));
    return t(kind === "complaint" ? "complaint_noted" : "officer_noted");
  }

  /* ---------------- voice ---------------- */
  let recorder = null;
  async function askVoice() {
    if (S.thinking) return;
    if (S.listening) { if (recorder) recorder.stop(); return; }
    S.error = null;
    if (!(LM.canRecord && LM.canRecord()) || !navigator.onLine) { askBrowserVoice(); return; }
    try { recorder = await LM.startRecording(15000); } catch (e) { recorder = null; askBrowserVoice(); return; }
    S.listening = true; render();
    const blob = await recorder.done;
    recorder = null; S.listening = false;
    if (!blob) { answerVoice({ record_again: true }); return; }
    S.thinking = true; render();
    let r;
    try { r = await LM.understandAudio(blob); }
    catch (e) {
      S.thinking = false;
      if (e.status === 422) { await answerVoice({ record_again: true, detail: e.detail }); return; }
      if (e.status === 503 || e.kind === "network") { S.flash = t("voice_off"); go("ask"); return; }
      S.error = errText(e); render(); return;
    }
    S.thinking = false; // answer with ONE render (a second render would clear the message)
    await answerVoice(r);
  }
  function askBrowserVoice() {
    if (typeof LM.listen !== "function") { go("ask"); return; }
    S.listening = true; render();
    let heard = "";
    LM.listen("ur", (text) => { heard = text; }, async () => {
      S.listening = false;
      if (!heard) { answerVoice({ record_again: true }); return; }
      await askText(heard);
    });
  }
  async function askText(text) {
    S.thinking = true; S.error = null; render();
    let r;
    try { r = await api("/voice/intent", { method: "POST", body: { text: text } }); }
    catch (e) { S.thinking = false; S.error = errText(e); render(); return; }
    S.thinking = false;
    await answerVoice(r);
  }
  /* The server only names WHAT is asked; the answer comes from this person's own claim. */
  async function answerVoice(r) {
    const c = current(), d = c && c.decision, ur = LM.lang() === "ur";
    const status = () => (!c ? t("no_claims") : c.status === "paid" ? t("paid_msg", { n: LM.fmt(c.amount) })
      : d ? (ur ? d.reason_ur : d.reason) : t("continue_step", { step: t("stepname_" + c.step) }));
    const answers = {
      lookup_claim_status: status,
      lookup_payment: () => (!c ? t("pay_none") : c.status === "paid" ? t("paid_msg", { n: LM.fmt(c.amount) })
        : c.status === "approved" ? t("pay_soon") : t("pay_wait")),
      show_required_documents: () => t("docs_needed"),
      start_application: () => (c && !["paid", "rejected", "withdrawn"].includes(c.status) ? t("continue_step", { step: t("stepname_" + c.step) }) : t("docs_needed")),
      explain_eligibility: () => t("eligibility"),
      handoff_to_officer: () => askOfficer("handoff"),
      file_complaint: () => askOfficer("complaint"),
      open_consent_page: () => t("consent_info"),
      report_fraud: () => t("fraud_info"),
      update_contact_details: () => t("update_info"),
      greet: () => t("greet", { name: S.me ? S.me.name : "" }),
      repeat_last: () => S.lastReply || t("say_again"),
    };
    let reply;
    if (r.record_again) reply = (r.detail && (ur ? r.detail.message_ur : r.detail.message_en)) || t("say_again");
    else if (!answers[r.action]) reply = t("say_again");
    else { try { reply = await answers[r.action](); } catch (e) { reply = errText(e); } }
    if (r.action !== "repeat_last") S.lastReply = reply;
    S.heard = r.text || null;
    S.flash = reply;
    if (r.action === "open_consent_page") await openPerms(true);
    else if (r.action === "report_fraud") go("msg");
    else if (r.action === "start_application" && !current()) go("home");
    else { if (S.screen === "ask") S.screen = "home"; render(); }
    if (typeof LM.speak === "function") LM.speak(reply, LM.lang() || "en");
  }
  function voiceBtn() {
    const label = S.thinking ? t("thinking") : S.listening ? t("tap_to_stop") : t("ask_voice");
    return bigBtn("🎤", label, askVoice, "primary" + (S.listening ? " rec" : ""), S.thinking ? { disabled: true } : {});
  }
  function screenAsk() {
    const ta = el("textarea", { id: "ask", rows: "3", placeholder: t("ask_hint"), "aria-label": t("ask_hint"), dir: "rtl",
                                oninput: (e) => { S.askText = e.target.value; } });
    ta.value = S.askText;
    const s = el("section", { class: "screen" }, el("h1", { text: t("ask_title") }));
    notes(s);
    s.append(ta);
    if (typeof LM.listen === "function") {
      s.append(bigBtn("🎤", S.listening ? t("listening") : t("speak"), () => {
        if (S.listening) return;
        S.listening = true; render();
        LM.listen("ur", (text) => { S.askText = (S.askText + " " + text).trim(); }, () => { S.listening = false; render(); });
      }, "", S.listening ? { disabled: true } : {}));
    }
    s.append(bigBtn("➤", S.thinking ? t("thinking") : t("ask_send"), () => {
      const q = S.askText.trim(); if (q && !S.thinking) { S.askText = ""; askText(q); }
    }, "go", S.thinking ? { disabled: true } : {}));
    s.append(bigBtn("←", t("back"), () => go("home"), "ghost"));
    return s;
  }

  /* ---------------- scam check ---------------- */
  async function checkMessage() {
    const text = S.msgText.trim();
    if (!text || S.busy) return;
    S.busy = true; S.error = null; S.verdict = null; render();
    try { S.verdict = await api("/ai/scam-check", { method: "POST", body: { text: text } }); }
    catch (e) { S.error = errText(e); }
    S.busy = false; render();
  }
  function screenMsg() {
    const ta = el("textarea", { id: "msg", rows: "6", placeholder: t("msg_hint"), "aria-label": t("msg_hint"),
                                oninput: (e) => { S.msgText = e.target.value; draft("msg", S.msgText); } });
    ta.value = S.msgText;
    const s = el("section", { class: "screen" }, el("h1", { text: t("msg_title") }));
    notes(s);
    s.append(ta, bigBtn("🔍", S.busy ? t("checking") : t("check"), checkMessage, "primary", S.busy ? { disabled: true } : {}));
    if (S.verdict) {
      const label = S.verdict.label, o = { scam: "red", safe: "green", unsure: "yellow" }[label] || "yellow";
      const text = t("v_" + (label in { scam: 1, safe: 1 } ? label : "unsure"));
      s.append(el("div", { class: "panel " + o, role: "status" },
        el("div", { class: "light " + o, "aria-hidden": "true", text: { red: "🛑", green: "✓", yellow: "?" }[o] }),
        el("p", { class: "reason", text: text }),
        el("p", { class: "next", text: t("scam_conf", { n: Math.round(S.verdict.scam_probability * 100) }) }), speakBtn(text)));
    }
    s.append(bigBtn("←", t("back"), () => { S.verdict = null; go("home"); }, "ghost"));
    return s;
  }

  /* ---------------- my permissions (consent page) ---------------- */
  async function openPerms(keepFlash) {
    const f = keepFlash ? S.flash : null;
    try { S.perms = await api("/consents"); } catch (e) { S.error = errText(e); }
    S.flash = f; go("perms");
  }
  async function permAction(path, body) {
    try { await api(path, { method: "POST", body: body }); S.flash = t("saved"); }
    catch (e) { S.error = e.status === 404 ? t("no_helper") : errText(e); render(); return; }
    await openPerms(true);
  }
  function screenPerms() {
    const ur = LM.lang() === "ur", s = el("section", { class: "screen" }, el("h1", { text: t("my_perms") }),
      el("p", { class: "muted", text: t("perms_intro") }));
    notes(s);
    const recs = (S.perms && S.perms.records) || [];
    const latest = {};
    recs.forEach((r) => { const k = r.purpose + (r.helper_email || ""); if (!(k in latest)) latest[k] = r; });
    ((S.perms && S.perms.purposes) || []).filter((p) => p.purpose !== "helper_access").forEach((p) => {
      const r = latest[p.purpose], on = r && r.status === "active";
      s.append(el("div", { class: "panel perm-row " + (on ? "green" : "yellow") },
        el("p", { class: "reason", text: ur ? p.ur : p.en }),
        el("p", { class: "next", text: on ? t("access_on") : r ? t("access_off") : t("access_never") }),
        on ? bigBtn("✋", t("stop_access"), () => permAction("/consents/" + r.id + "/withdraw"), "ghost")
           : bigBtn("✓", t("allow"), () => permAction("/consents", { purpose: p.purpose }), "ghost")));
    });
    s.append(el("h2", { text: t("my_helpers") }));
    Object.values(latest).filter((r) => r.purpose === "helper_access").forEach((r) => {
      const on = r.status === "active";
      s.append(el("div", { class: "panel " + (on ? "green" : "yellow") },
        el("p", { class: "reason", text: r.helper_name + " — " + t(on ? "access_on" : "access_off") }),
        on ? bigBtn("✋", t("stop_access"), () => permAction("/consents/" + r.id + "/withdraw"), "ghost")
           : bigBtn("✓", t("allow_again"), () => permAction("/consents", { purpose: "helper_access", helper_email: r.helper_email }), "ghost")));
    });
    const input = el("input", { type: "email", id: "hemail", placeholder: t("helper_email"), "aria-label": t("helper_email"),
                                oninput: (e) => { S.helperEmail = e.target.value; } });
    input.value = S.helperEmail;
    s.append(input, bigBtn("➕", t("add_helper"), () => {
      const v = S.helperEmail.trim(); if (v) { S.helperEmail = ""; permAction("/consents", { purpose: "helper_access", helper_email: v }); }
    }, "primary"));
    s.append(bigBtn("←", t("back"), () => go("home"), "ghost"));
    return s;
  }

  /* ---------------- helper mode ---------------- */
  function lostConsent() {
    localStorage.removeItem("lm_acting");
    S.family = null; S.claims = []; S.error = t("err_consent"); S.screen = "family";
  }
  async function loadFamilies() {
    S.families = await api("/helper/families");
    const id = localStorage.getItem("lm_acting");
    S.family = S.families.find((f) => String(f.citizen_id) === id) || null;
    if (!S.family) localStorage.removeItem("lm_acting");
  }
  async function chooseFamily(f) {
    try {
      await api("/helper/families/" + f.citizen_id + "/select", { method: "POST" });
      localStorage.setItem("lm_acting", String(f.citizen_id));
      S.family = f; await loadClaims(); go("home");
    } catch (e) { await loadFamilies().catch(() => {}); S.error = e.kind === "auth" ? t("err_consent") : errText(e); render(); }
  }
  function screenFamily() {
    const s = el("section", { class: "screen" }, el("h1", { text: t("whose_claim") }));
    notes(s);
    if (!S.families.length) s.append(el("p", { class: "muted", text: t("no_families") }));
    S.families.forEach((f) => s.append(bigBtn("👪", f.name, () => chooseFamily(f), "primary")));
    return s;
  }

  /* ---------------- home ---------------- */
  function screenLang() {
    return el("section", { class: "screen" }, el("h1", { text: "زبان چنیں / Choose language" }),
      bigBtn("🗣️", "اردو", () => { LM.setLang("ur"); afterLang(); }, "primary"),
      bigBtn("🗣️", "English", () => { LM.setLang("en"); afterLang(); }, "primary"));
  }
  const afterLang = () => go(isHelper() && !S.family ? "family" : "home");

  function screenHome() {
    const c = current();
    const s = el("section", { class: "screen" }, el("h1", { text: t("hello", { name: S.me.name }) }));
    if (isHelper() && S.family) s.append(el("p", { class: "flash", role: "status", text: t("helping", { name: S.family.name }) }));
    if (!navigator.onLine) s.append(el("p", { class: "flash", role: "status", text: t("offline_note") }));
    if (S.pending) s.append(el("p", { class: "flash", role: "status", text: t("waiting", { n: S.pending }) }));
    notes(s);
    s.append(bigBtn("🎙️", t("talk_assistant"), () => { location.href = "/assistant"; }, "primary"));
    if (c) s.append(decisionPanel(c));
    if (!c || ["paid", "rejected", "withdrawn"].includes(c.status)) {
      s.append(bigBtn("📝", S.busy ? t("sending") : t("start_claim"), startClaim, "go", S.busy ? { disabled: true } : {}));
    } else if (["draft", "waiting_citizen"].includes(c.status)) {
      s.append(bigBtn("➤", t("continue_claim"), openClaim, "go"));
    }
    if (S.heard) s.append(el("p", { class: "muted", text: t("you_asked", { text: S.heard }) }));
    s.append(voiceBtn(), bigBtn("⌨️", t("type_instead"), () => go("ask"), "ghost"));
    s.append(bigBtn("✉️", t("check_msg"), () => go("msg")));
    if (isHelper()) s.append(bigBtn("👪", t("switch_family"), () => go("family"), "ghost"));
    else s.append(bigBtn("🔐", t("my_perms"), () => openPerms(), "ghost"));
    s.append(bigBtn("🌐", t("change_lang"), () => go("lang"), "ghost"), bigBtn("🚪", t("logout"), LM.logout, "ghost"));
    return s;
  }

  function render() {
    LM.applyLang();
    $("who").textContent = S.me ? S.me.name + (S.family ? " → " + S.family.name : "") : "";
    const view = { lang: screenLang, home: screenHome, msg: screenMsg, family: screenFamily, perms: screenPerms, ask: screenAsk,
                   s_consent: screenConsent, s_identity: screenIdentity, s_elig: screenElig, s_review: screenReview,
                   s_result: screenResult }[S.screen] || screenHome;
    $("app").replaceChildren(view());
  }

  async function syncNow() {
    if (!navigator.onLine || !S.me) return;
    const r = await LM.queue.flush();
    await refreshPending();
    if (r.sent) { try { await loadClaims(); } catch (e) {} S.flash = t("sent_ok"); }
    if (r.dropped) S.error = t("err_photo");
    if (r.sent || r.dropped) render();
  }

  async function boot() {
    $("lang-btn").addEventListener("click", () => go("lang"));
    $("out-btn").addEventListener("click", LM.logout);
    try {
      S.me = await LM.requireRole(["citizen", "helper"]);
      if (!S.me) return;
    } catch (e) {
      if (e.kind !== "network") throw e;
      S.me = JSON.parse(localStorage.getItem("lm_me") || "null"); // offline start: the saved user
      if (!S.me) { $("app").textContent = t("err_net"); return; }
    }
    try { S.purposes = await api("/claims/purposes"); } catch (e) {}
    if (isHelper()) { try { await loadFamilies(); } catch (e) { S.error = errText(e); } }
    if (!isHelper() || S.family) { try { await loadClaims(); } catch (e) { S.error = errText(e); } }
    await refreshPending();
    S.screen = !LM.lang() ? "lang" : (isHelper() && !S.family ? "family" : "home");
    render();
    window.addEventListener("online", syncNow);
    window.addEventListener("offline", render);
    syncNow();
  }
  boot();
})();
