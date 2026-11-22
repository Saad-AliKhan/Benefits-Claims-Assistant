/* Sign in. Citizens: mobile + PIN, sign-up and PIN reset with a code to the mobile. Staff: email + password,
   and a temporary password must be replaced at the first sign-in. */
(function () {
  "use strict";
  const $ = (id) => document.getElementById(id), el = LM.el;
  const params = new URLSearchParams(location.search);
  let OPT = { codes_on_screen: true };
  LM.api("/auth/options").then((o) => { OPT = o; }).catch(() => {});

  function msg(e) {   // server messages come in Urdu + English
    const d = e && e.detail;
    if (d && typeof d === "object" && d.message_ur) return d.message_ur + " / " + d.message_en;
    return e.kind === "network" ? "کنکشن نہیں۔ دوبارہ کوشش کریں۔ / No connection. Try again." : (e.message || "Something went wrong");
  }
  function cErr(text) { $("c-err").hidden = !text; $("c-err").textContent = text || ""; }
  async function done(session) {
    localStorage.setItem("lm_token", session.access_token);
    localStorage.setItem("lm_me", JSON.stringify(session.user));
    localStorage.removeItem("lm_acting");
    if (session.user.must_change_password) { showChange(); return; }
    location.href = session.user.home;
  }

  // ---- citizen tabs
  document.querySelectorAll(".seg2 [data-v]").forEach((b) => b.addEventListener("click", () => {
    document.querySelectorAll(".seg2 [data-v]").forEach((x) => x.setAttribute("aria-selected", String(x === b)));
    ["in", "new", "reset"].forEach((v) => { $("f-" + v).hidden = v !== b.dataset.v; });
    cErr("");
  }));
  $("f-in").addEventListener("submit", async (ev) => {
    ev.preventDefault(); cErr("");
    try { await done(await LM.api("/auth/login/phone", { method: "POST", body: { phone: $("in-phone").value, pin: $("in-pin").value } })); }
    catch (e) { cErr(msg(e)); }
  });

  // step 2 of sign-up / PIN reset: the code (shown on screen while there is no SMS gateway) and a new PIN
  function codeStep(box, phone, sent, finishUrl) {
    const code = el("input", { class: "pin-input", inputmode: "numeric", maxlength: "6", required: true, id: box.id + "-code", autocomplete: "one-time-code" });
    const pin = el("input", { class: "pin-input", type: "password", inputmode: "numeric", maxlength: "6", required: true, id: box.id + "-pin", autocomplete: "new-password" });
    const pin2 = el("input", { class: "pin-input", type: "password", inputmode: "numeric", maxlength: "6", required: true, id: box.id + "-pin2" });
    const onScreen = sent.code_on_screen ? el("div", { class: "notice" },
      el("p", { class: "bi stack", style: "margin:0" }, el("span", { class: "ur", lang: "ur", text: "SMS سروس ابھی جڑی نہیں، اس لیے آپ کا کوڈ یہاں ہے:" }),
        el("span", { class: "en", text: "The SMS service is not connected yet, so your code is shown here:" })),
      el("div", { class: "code-box", text: sent.code_on_screen })) : null;
    const go = el("button", { class: "btn primary go-btn" }, el("span", { class: "ur", lang: "ur", text: "محفوظ کریں" }), el("span", { class: "en", text: "Save" }));
    box.replaceChildren(
      el("p", { class: "bi stack" }, el("span", { class: "ur", lang: "ur", text: "کوڈ " + phone + " پر بھیجا گیا، " + sent.minutes + " منٹ کے لیے" }),
        el("span", { class: "en", text: "A code was sent to " + phone + " (valid " + sent.minutes + " minutes)" })),
      onScreen,
      el("div", { class: "field" }, el("label", { for: code.id, class: "bi" }, el("span", { class: "ur", lang: "ur", text: "کوڈ" }), el("span", { class: "en", text: "Code" })), code),
      el("div", { class: "field" }, el("label", { for: pin.id, class: "bi" }, el("span", { class: "ur", lang: "ur", text: "نیا پن (4 سے 6 ہندسے)" }),
        el("span", { class: "en", text: "New PIN, 4 to 6 digits. Not 1234 or 1111." })), pin),
      el("div", { class: "field" }, el("label", { for: pin2.id, class: "bi" }, el("span", { class: "ur", lang: "ur", text: "پن دوبارہ" }), el("span", { class: "en", text: "PIN again" })), pin2),
      go);
    box.hidden = false;
    go.addEventListener("click", async (ev) => {
      ev.preventDefault(); cErr("");
      if (pin.value !== pin2.value) { cErr("دونوں پن ایک جیسے نہیں۔ / The two PINs are different."); return; }
      try { await done(await LM.api(finishUrl, { method: "POST", body: { phone: phone, code: code.value, pin: pin.value } })); }
      catch (e) { cErr(msg(e)); }
    });
    code.focus();
  }
  $("f-new").addEventListener("submit", async (ev) => {
    ev.preventDefault(); cErr("");
    const phone = $("new-phone").value;
    try {
      const sent = await LM.api("/auth/signup/start", { method: "POST", body: { full_name: $("new-name").value, cnic: $("new-cnic").value, phone: phone } });
      $("new-a").hidden = true; codeStep($("new-b"), phone, sent, "/auth/signup/finish");
    } catch (e) { cErr(msg(e)); }
  });
  $("f-reset").addEventListener("submit", async (ev) => {
    ev.preventDefault(); cErr("");
    const phone = $("reset-phone").value;
    try {
      const sent = await LM.api("/auth/pin-reset/start", { method: "POST", body: { phone: phone } });
      $("reset-a").hidden = true; codeStep($("reset-b"), phone, sent, "/auth/pin-reset/finish");
    } catch (e) { cErr(msg(e)); }
  });

  // ---- staff
  function showStaff() { $("staff").hidden = false; $("staff-link").hidden = true; $("email").focus(); }
  $("staff-link").addEventListener("click", showStaff);
  $("f-staff").addEventListener("submit", async (ev) => {
    ev.preventDefault(); $("err").hidden = true;
    try { await done(await LM.api("/auth/login", { method: "POST", body: { email: $("email").value.trim(), password: $("pw").value } })); }
    catch (e) { $("err").hidden = false; $("err").textContent = e.kind === "network" ? "No connection. Try again." : msg(e).split(" / ").pop(); }
  });
  document.querySelectorAll(".demo [data-e]").forEach((b) => b.addEventListener("click", () => {
    showStaff(); $("email").value = b.dataset.e; $("pw").value = "demo1234"; $("pw").focus();
  }));

  // ---- first sign-in with a temporary password
  function showChange() {
    ["citizen", "staff", "demo"].forEach((id) => { if ($(id)) $(id).hidden = true; });
    $("staff-link").hidden = true; $("change").hidden = false; $("ch-cur").focus();
  }
  $("f-change").addEventListener("submit", async (ev) => {
    ev.preventDefault(); $("ch-err").hidden = true;
    if ($("ch-new").value !== $("ch-new2").value) { $("ch-err").hidden = false; $("ch-err").textContent = "The two new passwords are different."; return; }
    try { await done(await LM.api("/auth/change-password", { method: "POST", body: { current: $("ch-cur").value, new: $("ch-new").value } })); }
    catch (e) { $("ch-err").hidden = false; $("ch-err").textContent = e.message; }
  });

  // already signed in (e.g. opened from the home-screen icon): go to her page, or finish the password change
  if (LM.token()) LM.api("/auth/me").then((me) => {
    if (me.must_change_password || params.get("change")) showChange(); else location.replace(me.home);
  }).catch(() => {});
})();
