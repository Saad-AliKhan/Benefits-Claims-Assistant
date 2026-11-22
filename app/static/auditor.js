/* Auditor: evaluation numbers, every decision with its full trace, the audit log, consent records. Read-only. */
(function () {
  "use strict";
  const el = LM.el, api = LM.api, $ = (id) => document.getElementById(id);
  function toast(msg) { const t = $("toast"); t.textContent = msg; t.className = "bad"; t.hidden = false;
    clearTimeout(toast.h); toast.h = setTimeout(() => { t.hidden = true; }, 4000); }
  const table = (head, rows) => el("table", { class: "tbl" }, el("thead", {}, el("tr", {}, head.map((h) => el("th", { text: h })))),
    el("tbody", {}, rows.map((r) => el("tr", {}, r.map((c) => el("td", {}, c === null || c === undefined ? "–" : c))))));
  const pct = (x) => (x === null || x === undefined ? "–" : Math.round(x * 100) + "%");
  const stat = (n, label, cls) => el("div", { class: "stat " + (cls || "") }, el("b", { text: String(n) }), el("span", { text: label }));

  function evalRun(title, run) {
    const s = run.summary;
    return el("div", { class: "d-sec" }, el("h2", { text: title }),
      el("p", { class: "muted", text: s.claims + " fake claims (" + s.genuine + " genuine, " + s.should_not_pay +
        " that should not be paid) · rule version " + s.rule_version + " · " + LM.when(s.ran_at) }),
      el("div", { class: "stats" }, stat(s.auto_approved, "auto-approved", "green"), stat(s.asked_for_proof, "asked for proof", "yellow"),
        stat(s.sent_to_person, "sent to a person", "red"), stat(s.wrongly_blocked + " / " + s.genuine, "genuine claims not auto-approved (wrongly blocked)"),
        stat(s.wrongly_approved + " / " + s.should_not_pay, "bad claims paid automatically (wrongly approved)", s.wrongly_approved ? "red" : "green")),
      el("details", {}, el("summary", { text: "Every claim" }),
        table(["Id", "Scenario", "Should pay", "Result", "AI outcome", "Confidence", "Why (hidden truth)"],
          run.cases.map((r) => [r.id, r.label, r.should_pay ? "yes" : "no", r.zone.replace(/_/g, " "), r.outcome, pct(r.confidence), r.why]))));
  }

  async function loadEval() {
    const box = $("eval");
    const sm = await api("/audit/summary");
    box.replaceChildren(el("h2", { text: "Live data" }), el("div", { class: "stats" },
      ...Object.entries(sm.cases_by_status).map(([k, v]) => stat(v, "claims " + k.replace(/_/g, " "))),
      stat(sm.audit_entries, "audit log entries")));
    try {
      const ev = await api("/audit/evaluation");
      const runs = ev.runs || { plain: { summary: ev.summary, cases: ev.cases } };
      if (runs.plain) box.append(evalRun("Evaluation: typed details only (no photos)", runs.plain));
      if (runs.documents) box.append(evalRun("Evaluation: with SPECIMEN photos read by the OCR engine", runs.documents));
      box.append(el("p", { class: "muted", text: "Run again: python -m tools.evaluate_claims  (add --documents for photos)." }));
    } catch (e) { box.append(el("p", { class: "muted", text: e.message })); }
  }

  async function loadDecisions() {
    const ds = await api("/audit/decisions?limit=100");
    $("dec").replaceChildren(...ds.map((d) => el("details", { class: "d-sec" },
      el("summary", {}, el("span", { class: "chip " + d.outcome, text: d.outcome }), " Claim #" + d.case_id + " · confidence " + pct(d.confidence) +
        " · rule v" + d.rule_version + " · " + LM.when(d.created_at)),
      el("p", {}, el("b", { text: "Citizen was told: " }), d.reason_user),
      el("ul", { class: "why" }, d.trace.checks.map((c) => el("li", { class: c.severity, text: c.step + " [" + c.severity + "]: " + c.detail }))),
      el("pre", { class: "trace", text: JSON.stringify(d.trace, null, 1) }))));
    if (!ds.length) $("dec").replaceChildren(el("p", { class: "empty", text: "No decisions yet." }));
  }

  async function loadLog(ev) {
    if (ev) ev.preventDefault();
    const q = new URLSearchParams({ limit: "200" });
    if ($("f-action").value) q.set("action", $("f-action").value);
    if ($("f-role").value) q.set("actor_role", $("f-role").value);
    if ($("f-case").value) q.set("case_id", $("f-case").value);
    const r = await api("/audit/log?" + q);
    $("log-list").replaceChildren(el("p", { class: "muted", text: r.total + " entries (newest first). Entries can never be changed or deleted." }),
      table(["#", "When", "Who", "Action", "Claim", "Details"], r.items.map((a) => [String(a.id), LM.when(a.at),
        (a.actor || "") + " (" + a.actor_role + ")", el("code", { text: a.action }), a.case_id ? "#" + a.case_id : "",
        el("span", { class: "small", text: JSON.stringify(a.details) })])));
  }

  async function loadConsents() {
    const cs = await api("/audit/consents");
    $("cons").replaceChildren(table(["#", "Citizen", "Purpose", "Shared with", "Status", "Given", "Withdrawn"], cs.map((c) => [
      String(c.id), "#" + c.citizen_id, c.purpose, c.grantee + (c.helper_id ? " #" + c.helper_id : ""),
      el("span", { class: "chip " + (c.status === "active" ? "green" : "yellow"), text: c.status }), LM.when(c.granted_at), LM.when(c.withdrawn_at)])));
  }

  document.querySelectorAll("[data-tab]").forEach((b) => b.addEventListener("click", () => {
    document.querySelectorAll("[data-tab]").forEach((x) => x.classList.toggle("on", x === b));
    document.querySelectorAll(".tab").forEach((t) => { t.hidden = t.id !== b.dataset.tab; });
    ({ eval: loadEval, dec: loadDecisions, log: loadLog, cons: loadConsents })[b.dataset.tab]().catch((e) => toast(e.message));
  }));
  $("log-form").addEventListener("submit", (ev) => loadLog(ev).catch((e) => toast(e.message)));
  (async () => { const me = await LM.requireRole(["auditor", "admin"]); if (!me) return; LM.topbar(me); loadEval().catch((e) => toast(e.message)); })();
})();
