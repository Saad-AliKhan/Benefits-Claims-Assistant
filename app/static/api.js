/* Shared helpers for every screen. Login = a JWT from /auth/login, kept on this device and sent as
   "Authorization: Bearer ..." with every API call. The server checks the role on every call. */
(function () {
  "use strict";
  const LM = (window.LM = window.LM || {});

  LM.token = () => localStorage.getItem("lm_token");
  LM.getUid = () => { try { return String(JSON.parse(localStorage.getItem("lm_me") || "{}").id || ""); } catch (e) { return ""; } };
  LM.authHeaders = () => {
    const h = LM.token() ? { Authorization: "Bearer " + LM.token() } : {};
    h["ngrok-skip-browser-warning"] = "1";   // free ngrok link (phone.bat): no warning page for API calls
    const acting = localStorage.getItem("lm_acting");
    if (acting) h["X-Acting-For"] = acting; // helper: which family
    return h;
  };
  LM.login = async function (email, password) {
    const r = await LM.api("/auth/login", { method: "POST", body: { email: email, password: password } });
    localStorage.setItem("lm_token", r.access_token);
    localStorage.setItem("lm_me", JSON.stringify(r.user));
    localStorage.removeItem("lm_acting");
    return r.user;
  };
  LM.logout = async () => {
    try { await LM.api("/auth/logout", { method: "POST" }); } catch (e) {}
    ["lm_token", "lm_me", "lm_acting"].forEach((k) => localStorage.removeItem(k));
    location.href = "/login";
  };

  /* fetch wrapper: JSON in / JSON out. Errors carry .kind = "network" | "auth" | "http" and .status */
  LM.api = async function (path, opts) {
    opts = opts || {};
    const headers = Object.assign({}, LM.authHeaders(), opts.headers || {});
    let body = opts.body;
    if (body && !(body instanceof FormData) && typeof body === "object") {
      body = JSON.stringify(body);
      headers["Content-Type"] = "application/json";
    }
    let res;
    try {
      res = await fetch(path, { method: opts.method || "GET", headers: headers, body: body });
    } catch (e) {
      const err = new Error("network");
      err.kind = "network";
      throw err;
    }
    let data = null;
    try {
      data = await res.json();
    } catch (e) {}
    if (!res.ok) {
      let detail = data && data.detail;
      if (detail && typeof detail === "object" && !Array.isArray(detail)) detail = detail.message_en || detail.code;
      if (Array.isArray(detail)) detail = detail.map((d) => d.msg).join("; ");
      const err = new Error((typeof detail === "string" && detail) || res.statusText || "error");
      err.status = res.status;
      err.detail = data && data.detail; // e.g. {message_ur, message_en} from the voice / OCR checks
      err.kind = res.status === 401 || res.status === 403 ? "auth" : "http";
      throw err;
    }
    return data;
  };

  /* Build DOM safely (never innerHTML: names, notes and OCR text come from users). */
  LM.el = function (tag, attrs) {
    const n = document.createElement(tag);
    const a = attrs || {};
    Object.keys(a).forEach(function (k) {
      const v = a[k];
      if (v === null || v === undefined || v === false) return;
      if (k === "class") n.className = v;
      else if (k === "text") n.textContent = v;
      else if (k.slice(0, 2) === "on" && typeof v === "function") n.addEventListener(k.slice(2), v);
      else n.setAttribute(k, v === true ? "" : v);
    });
    for (let i = 2; i < arguments.length; i++) {
      [].concat(arguments[i]).forEach(function (kid) {
        if (kid === null || kid === undefined || kid === false) return;
        n.append(kid.nodeType ? kid : document.createTextNode(String(kid)));
      });
    }
    return n;
  };

  /* Make sure someone is logged in with one of the allowed roles, else go to /login. */
  LM.requireRole = async function (roles) {
    if (!LM.token()) { location.replace("/login"); return null; }
    try {
      const me = await LM.api("/auth/me");
      localStorage.setItem("lm_me", JSON.stringify(me));
      if (me.must_change_password) { location.replace("/login?change=1"); return null; }   // temporary password first
      if (roles.indexOf(me.role) === -1) { location.replace(me.home || "/login"); return null; }
      return me;
    } catch (e) {
      if (e.status === 401) { localStorage.removeItem("lm_token"); location.replace("/login"); return null; }
      throw e;
    }
  };

  /* Staff pages: name + role + log out in the top bar. */
  LM.topbar = function (me) {
    const who = document.getElementById("who");
    if (who) who.replaceChildren(LM.el("b", { text: me.name }), LM.el("div", { class: "small", text: me.email || me.phone || me.role }));
    const out = document.getElementById("out");
    if (out) out.addEventListener("click", LM.logout);
  };
  LM.when = (iso) => (iso ? new Date(/Z$|[+-]\d\d:?\d\d$/.test(iso) ? iso : iso + "Z").toLocaleString() : "");

  LM.fmt = (n) => Number(n || 0).toLocaleString("en-US");

  /* Phone app: the site installs like an app (home-screen icon, full screen, opens on the assistant).
     Chrome offers it after "beforeinstallprompt"; we show one big button for it. */
  if ("serviceWorker" in navigator && !navigator.serviceWorker.controller) {
    window.addEventListener("load", () => navigator.serviceWorker.register("/sw.js").catch(() => {}));
  }
  /* The Android app (android/): it shows these same pages; the page knows by the user agent. */
  LM.inApp = () => /AasraApp\//.test(navigator.userAgent);
  LM.onAndroid = () => /Android/i.test(navigator.userAgent);
  LM.appLink = () => "intent://setup?server=" + encodeURIComponent(location.origin) +
    "#Intent;scheme=aasra;package=pk.aasra.app;S.browser_fallback_url=" +
    encodeURIComponent(location.origin + "/app") + ";end";
  window.addEventListener("DOMContentLoaded", () => {
    // In an Android browser (not in the app): offer the app; in the app: nothing to install.
    if (!LM.onAndroid() || LM.inApp() || location.pathname !== "/login" || document.getElementById("get-app")) return;
    const a = LM.el("a", { id: "get-app", class: "install", href: LM.appLink() }, "📲 ایپ میں کھولیں · Open in app");
    document.body.append(a);
  });

  let installEvent = null;
  window.addEventListener("beforeinstallprompt", (e) => {
    e.preventDefault();
    if (LM.inApp() || LM.onAndroid()) return;   // Android: the native app is offered instead
    installEvent = e;
    if (document.getElementById("install-app")) return;
    const b = LM.el("button", { id: "install-app", class: "install", type: "button" }, "📲 ایپ انسٹال کریں · Install app");
    b.addEventListener("click", async () => {
      if (!installEvent) return;
      installEvent.prompt();
      try { await installEvent.userChoice; } catch (err) {}
      installEvent = null; b.remove();
    });
    document.body.append(b);
  });
  window.addEventListener("appinstalled", () => { const b = document.getElementById("install-app"); if (b) b.remove(); });
})();
