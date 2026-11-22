/* Officer queue: claims the system sent to a person ("I am not sure" handoff), sorted by priority and
   confidence. Only claims the citizen shares with officers are listed. English only (staff screen). */
(function () {
  "use strict";
  const el = LM.el, api = LM.api;
  const $ = (id) => document.getElementById(id);
  const S = { me: null, items: [], sort: "priority", filter: "", selected: null, detail: null, photos: {} };
  const pct = (x) => (x === null || x === undefined ? "–" : Math.round(x * 100) + "%");
  const ago = (m) => (m < 1 ? "just now" : m < 60 ? m + " min" : m < 1440 ? Math.round(m / 60) + " h" : Math.round(m / 1440) + " d");
  const STATUS = { escalated: "Needs an officer", assigned: "Being reviewed", payment_failed: "Payment failed",
                   waiting_citizen: "Waiting for the citizen", approved: "Approved", paid: "Paid", rejected: "Rejected" };
  const COLOR = { escalated: "red", assigned: "red", payment_failed: "red", waiting_citizen: "yellow", paid: "green", approved: "green" };

  function toast(msg, bad) {
    const t = $("toast"); t.textContent = msg; t.className = bad ? "bad" : ""; t.hidden = false;
    clearTimeout(toast.h); toast.h = setTimeout(() => { t.hidden = true; }, 3500);
  }
  const errMsg = (e) => (e.kind === "network" ? "No connection. Try again." : e.message || "Something went wrong.");

  async function loadQueue() {
    try {
      const q = await api("/officer/queue?sort=" + S.sort);
      S.items = q.items;
      $("how").textContent = "How this is sorted: " + q.how_sorted;
      $("c-all").textContent = q.items.length;
      $("c-off").textContent = q.items.filter((i) => i.waiting_on === "officer").length;
      $("c-mine").textContent = q.items.filter((i) => i.assigned_to_me).length;
      $("c-cit").textContent = q.items.filter((i) => i.waiting_on === "citizen").length;
      renderList();
    } catch (e) { if (e.status === 401) return location.replace("/login"); toast(errMsg(e), true); }
  }

  function row(i) {
    return el("button", { type: "button", class: "q-row " + (COLOR[i.status] || "") + (i.case_id === S.selected ? " sel" : ""),
                          onclick: () => openCase(i.case_id) },
      el("span", { class: "prio", title: "Priority score", text: String(i.priority) }),
      el("span", { class: "q-main" }, el("strong", { text: "Claim #" + i.case_id + " · " + i.citizen_name }),
        el("span", { class: "muted", text: i.headline })),
      el("span", { class: "q-meta" },
        el("span", { class: "chip " + (COLOR[i.status] || ""), text: STATUS[i.status] || i.status }),
        i.assigned_to_me ? el("span", { class: "chip on", text: "Mine" }) : null,
        el("span", { text: "Confidence " + pct(i.confidence) }), el("span", { text: "PKR " + LM.fmt(i.amount) }),
        el("span", { class: "muted", text: ago(i.age_minutes) })));
  }

  function renderList() {
    const f = S.filter, items = S.items.filter((i) => !f || (f === "mine" ? i.assigned_to_me : i.waiting_on === f));
    $("list").replaceChildren(...(items.length ? items.map(row) : [el("p", { class: "empty", text: "Nothing waiting." })]));
  }

  async function openCase(id) {
    S.selected = id; renderList();
    try { S.detail = await api("/officer/cases/" + id); renderDetail(); }
    catch (e) { toast(errMsg(e), true); }
  }

  const section = (title, ...kids) => el("section", { class: "d-sec" }, el("h3", { text: title }), ...kids);
  const kv = (k, v) => [el("span", { class: "k", text: k }), el("span", { text: v === null || v === undefined || v === "" ? "–" : String(v) })];

  async function photo(doc, box) {  // photos need the login token, so fetch them instead of <img src>
    try {
      const res = await fetch(doc.photo_url, { headers: LM.authHeaders() });
      if (!res.ok) throw new Error();
      box.replaceChildren(el("img", { class: "doc-img", src: URL.createObjectURL(await res.blob()), alt: doc.doc_type + " photo" }));
    } catch (e) { box.replaceChildren(el("span", { class: "muted", text: "Photo not available." })); }
  }

  function renderDetail() {
    const d = S.detail, c = d.case, dec = d.decision, box = $("detail");
    box.hidden = false;
    const ident = ((c.data || {}).identity || {}), elig = ((c.data || {}).eligibility || {});
    const problems = dec ? dec.trace.checks.filter((x) => x.severity !== "green") : [];
    const kids = [
      el("h2", { text: "Claim #" + c.id + " · " + d.citizen.name }),
      el("p", {}, el("span", { class: "chip " + (COLOR[c.status] || ""), text: STATUS[c.status] || c.status }), " ",
        el("span", { text: "PKR " + LM.fmt(c.amount) + " · AI confidence " + pct(c.confidence) +
                           (dec ? " · rule version " + dec.rule_version : "") })),
    ];
    if (!d.shared_with_officers) kids.push(el("p", { class: "err", text: "The citizen has withdrawn sharing with officers." }));
    kids.push(section("Why it is here", el("ul", { class: "why" }, problems.length
      ? problems.map((p) => el("li", { class: p.severity, text: p.step + ": " + p.detail })) : [el("li", { text: "Payment or a citizen request." })])));
    kids.push(section("What was checked", el("div", { class: "kv" },
      kv("Citizen CNIC", d.citizen.cnic), kv("Registry name", ((ident.result || {}).registry || {}).full_name),
      kv("Name match", ((ident.result || {}).name_match || {}).status), kv("Identity", (ident.result || {}).action),
      kv("Deceased CNIC", (elig.input || {}).deceased_cnic), kv("Relation", (elig.input || {}).relation),
      kv("Death record", (elig.result || {}).record_found ? "found" : "not found"), kv("Eligibility", (elig.result || {}).action),
      kv("Payment ref", c.payment_ref))));
    if (d.documents.length) {
      kids.push(section("Documents (read by the OCR engine)", ...d.documents.map((doc) => {
        const ph = el("div", { class: "doc-photo" }, el("span", { class: "muted", text: "Loading photo…" }));
        photo(doc, ph);
        const fields = doc.fields || {};
        return el("div", { class: "doc" },
          el("p", {}, el("strong", { text: doc.doc_type === "cnic" ? "CNIC" : "Death certificate" }),
            " · " + doc.source + " · " + doc.action + " · confidence " + pct(doc.overall_confidence)),
          el("div", { class: "kv small" }, ...Object.keys(fields).flatMap((k) => kv(k, fields[k]))),
          el("div", { class: "flags" }, (doc.flags || []).length ? doc.flags.map((f) => el("span", { class: "chip", text: f }))
            : el("span", { class: "muted", text: "No flags." })), ph);
      })));
    }
    kids.push(section("Notes", el("ul", { class: "notes" }, d.notes.length
      ? d.notes.map((n) => el("li", {}, el("span", { class: "muted", text: LM.when(n.at) + " · " + n.by + ": " }),
          el("span", { class: "pre", text: n.note })))
      : [el("li", { class: "muted", text: "No notes." })])));
    const note = el("textarea", { id: "note", rows: "2", placeholder: "Add a note (required to reject)", class: "o-note" });
    const acts = el("div", { class: "actions" });
    if (["escalated", "payment_failed", "waiting_citizen"].includes(c.status) && S.me.role === "officer")
      acts.append(el("button", { type: "button", class: "btn primary", onclick: () => act("/assign", null, "Taken") }, "Take this claim"));
    if (c.status === "assigned" && c.assigned_to_me) {
      acts.append(el("button", { type: "button", class: "btn primary", onclick: () => act("/decision", { approve: true, note: note.value }, "Approved") }, "Approve and pay"),
                  el("button", { type: "button", class: "btn danger", onclick: () => act("/decision", { approve: false, note: note.value }, "Rejected") }, "Reject"));
    }
    if (["approved", "payment_failed"].includes(c.status) && S.me.role === "officer" && c.status === "approved")
      acts.append(el("button", { type: "button", class: "btn", onclick: () => act("/retry-payment", null, "Payment sent again") }, "Retry payment"));
    acts.append(el("button", { type: "button", class: "btn", onclick: () => {
      if (!note.value.trim()) return toast("Write a note first", true);
      act("/notes", { note: note.value.trim() }, "Note added");
    } }, "Add note"));
    kids.push(section("Your decision", note, acts));
    if (dec) kids.push(section("Full trace (for the auditor)", el("details", {}, el("summary", { text: "Show" }),
      el("pre", { class: "trace", text: JSON.stringify(dec.trace, null, 1) }))));
    box.replaceChildren(...kids);
  }

  async function act(path, body, ok) {
    try {
      await api("/officer/cases/" + S.selected + path, { method: "POST", body: body || undefined });
      toast(ok); await loadQueue(); await openCase(S.selected);
    } catch (e) { toast(errMsg(e), true); }
  }

  async function boot() {
    S.me = await LM.requireRole(["officer", "admin"]);
    if (!S.me) return;
    LM.topbar(S.me);
    $("sort").addEventListener("change", (e) => { S.sort = e.target.value; loadQueue(); });
    $("refresh").addEventListener("click", loadQueue);
    document.querySelectorAll("#filters [data-f]").forEach((b) => b.addEventListener("click", () => {
      document.querySelectorAll("#filters [data-f]").forEach((x) => x.classList.remove("on"));
      b.classList.add("on"); S.filter = b.dataset.f; renderList();
    }));
    await loadQueue();
  }
  boot();
})();
