/* Admin: rule editor (versioned), API keys, users. */
(function () {
  "use strict";
  const el = LM.el, api = LM.api, $ = (id) => document.getElementById(id);
  function toast(msg, bad) { const t = $("toast"); t.textContent = msg; t.className = bad ? "bad" : ""; t.hidden = false;
    clearTimeout(toast.h); toast.h = setTimeout(() => { t.hidden = true; }, 4000); }
  const table = (head, rows) => el("table", { class: "tbl" }, el("thead", {}, el("tr", {}, head.map((h) => el("th", { text: h })))),
    el("tbody", {}, rows.map((r) => el("tr", {}, r.map((c) => el("td", {}, c === null || c === undefined ? "–" : c))))));

  async function loadRules() {
    const r = await api("/admin/rules"), form = $("rule-form");
    const inputs = {};
    form.replaceChildren(el("p", {}, el("strong", { text: "Active: version " + r.version }), " · " + (r.note || "") + " · " + LM.when(r.created_at)),
      ...Object.keys(r.config).map((k) => {
        const lim = r.limits[k] || [0, 1];
        const step = Number.isInteger(r.config[k]) && lim[1] > 1 ? "1" : "0.01";
        inputs[k] = el("input", { type: "number", id: "r_" + k, value: r.config[k], min: lim[0], max: lim[1], step: step });
        return el("div", { class: "rule" }, el("label", { for: "r_" + k }, el("code", { text: k })), inputs[k],
          el("span", { class: "muted", text: r.help[k] || "" }));
      }),
      el("div", { class: "rule" }, el("label", { for: "r_note", text: "Why (note)" }), el("input", { id: "r_note", placeholder: "e.g. stricter after audit" })),
      el("button", { class: "btn primary", type: "submit" }, "Save as a new version"));
    form.onsubmit = async (ev) => {
      ev.preventDefault();
      const changes = {};
      Object.keys(inputs).forEach((k) => { const v = Number(inputs[k].value); if (v !== r.config[k]) changes[k] = v; });
      if (!Object.keys(changes).length) return toast("Nothing changed", true);
      try { const n = await api("/admin/rules", { method: "POST", body: { changes: changes, note: $("r_note").value } });
        toast("Saved: version " + n.version); await loadRules(); }
      catch (e) { toast(e.message, true); }
    };
    const hist = await api("/admin/rules/history");
    $("history").replaceChildren(table(["Version", "When", "Note", "Changed", ""], hist.map((h, i) => {
      const prev = hist[i + 1], diff = prev ? Object.keys(h.config).filter((k) => h.config[k] !== prev.config[k])
        .map((k) => k + ": " + prev.config[k] + " → " + h.config[k]).join("; ") : "initial";
      return [String(h.version), LM.when(h.created_at), h.note, diff || "no change",
        i === 0 ? el("span", { class: "chip on", text: "active" }) : el("button", { type: "button", class: "btn", onclick: async () => {
          try { await api("/admin/rules/rollback/" + h.version, { method: "POST" }); toast("Rolled back (saved as a new version)"); loadRules(); }
          catch (e) { toast(e.message, true); } } }, "Use again")];
    })));
  }

  async function loadKeys() {
    const keys = await api("/admin/api-keys");
    $("key-list").replaceChildren(table(["Name", "Starts with", "Created", "Last used", "Status", ""], keys.map((k) => [
      k.name, el("code", { text: k.prefix + "…" }), LM.when(k.created_at), LM.when(k.last_used_at),
      k.revoked_at ? "revoked" : "active",
      k.revoked_at ? "" : el("button", { type: "button", class: "btn danger", onclick: async () => {
        await api("/admin/api-keys/" + k.id + "/revoke", { method: "POST" }); toast("Revoked"); loadKeys(); } }, "Revoke")])));
  }
  $("key-form").addEventListener("submit", async (ev) => {
    ev.preventDefault();
    try { const k = await api("/admin/api-keys", { method: "POST", body: { name: $("key-name").value } });
      $("new-key").hidden = false; $("new-key").replaceChildren("Copy this key now, it is not shown again: ", el("code", { text: k.api_key }));
      $("key-name").value = ""; loadKeys(); }
    catch (e) { toast(e.message, true); }
  });

  async function loadUsers() {
    const us = await api("/admin/users");
    $("user-list").replaceChildren(table(["Id", "Name", "Email", "Role"], us.map((u) => [String(u.id), u.name, u.email, u.role])));
  }

  document.querySelectorAll("[data-tab]").forEach((b) => b.addEventListener("click", () => {
    document.querySelectorAll("[data-tab]").forEach((x) => x.classList.toggle("on", x === b));
    document.querySelectorAll(".tab").forEach((t) => { t.hidden = t.id !== b.dataset.tab; });
    ({ rules: loadRules, keys: loadKeys, users: loadUsers })[b.dataset.tab]().catch((e) => toast(e.message, true));
  }));

  (async () => { const me = await LM.requireRole(["admin"]); if (!me) return; LM.topbar(me); loadRules().catch((e) => toast(e.message, true)); })();
})();
