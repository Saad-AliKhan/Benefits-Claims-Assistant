/* Offline queue (IndexedDB) for claim steps with photos, photo shrinking, service worker registration. */
(function () {
  "use strict";
  const LM = (window.LM = window.LM || {});
  const DB = "lm_offline", STORE = "photos";

  function open() {
    return new Promise((res, rej) => {
      const r = indexedDB.open(DB, 1);
      r.onupgradeneeded = () => r.result.createObjectStore(STORE, { keyPath: "key" });
      r.onsuccess = () => res(r.result);
      r.onerror = () => rej(r.error);
    });
  }
  function tx(mode, fn) {
    return open().then((db) => new Promise((res, rej) => {
      const t = db.transaction(STORE, mode);
      const out = fn(t.objectStore(STORE));
      t.oncomplete = () => res(out.result);
      t.onerror = () => rej(t.error);
    }));
  }

  let flushing = false;
  LM.queue = {
    add: (item) => tx("readwrite", (s) => s.put(Object.assign({ uid: LM.getUid(), at: Date.now() }, item))),
    remove: (key) => tx("readwrite", (s) => s.delete(key)),
    mine: () => tx("readonly", (s) => s.getAll()).then((all) => all.filter((x) => x.uid === LM.getUid())),
    count: () => LM.queue.mine().then((a) => a.length).catch(() => 0),
    /* Send everything waiting. Same Idempotency-Key every time, so a retry can never create a duplicate. */
    flush: async function () {
      const r = { sent: 0, dropped: 0 };
      if (flushing) return r;
      flushing = true;
      try {
        for (const it of await LM.queue.mine()) {
          try {
            await LM.postStep(it);
            await LM.queue.remove(it.key);
            r.sent++;
          } catch (e) {
            if (e.kind === "network" || e.kind === "auth" || e.status >= 500) break; // try again later
            await LM.queue.remove(it.key); // 4xx: this photo can never succeed
            r.dropped++;
          }
        }
      } finally { flushing = false; }
      return r;
    },
  };

  /* One claim step (identity / eligibility) with its typed fields and an optional photo.
     item = { key, caseId, step, fields: {...}, blob, name }. Sent again from the queue after a dropped signal. */
  LM.postStep = function (it) {
    const fd = new FormData();
    Object.keys(it.fields || {}).forEach((k) => { if (it.fields[k]) fd.append(k, it.fields[k]); });
    if (it.blob) fd.append(it.step === "identity" ? "photo" : "certificate", it.blob, it.name || "photo.jpg");
    return LM.api("/claims/" + it.caseId + "/" + it.step, {
      method: "POST", body: fd, headers: { "Idempotency-Key": it.key },
    });
  };

  /* Big phone photos (4-8 MB) are hopeless on a weak signal: shrink anything over 1.5 MB.
     Long side 2000 px keeps a whole death certificate readable for the OCR service. */
  LM.shrink = async function (file, maxSide, quality) {
    if (file.size < 1.5 * 1024 * 1024) return file;
    maxSide = maxSide || 2000; quality = quality || 0.8;
    const bmp = await createImageBitmap(file);
    const k = Math.min(1, maxSide / Math.max(bmp.width, bmp.height));
    const c = document.createElement("canvas");
    c.width = Math.round(bmp.width * k); c.height = Math.round(bmp.height * k);
    c.getContext("2d").drawImage(bmp, 0, 0, c.width, c.height);
    const blob = await new Promise((r) => c.toBlob(r, "image/jpeg", quality));
    return blob && blob.size < file.size ? blob : file;
  };

  if ("serviceWorker" in navigator) {
    window.addEventListener("load", () => navigator.serviceWorker.register("/sw.js").catch(() => {}));
  }
})();