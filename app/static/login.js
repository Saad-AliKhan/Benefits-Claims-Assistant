/* Log in with email + password (JWT), then go to the page for this role. */
(function () {
  "use strict";
  const $ = (id) => document.getElementById(id);
  document.querySelectorAll(".demo [data-e]").forEach((b) => b.addEventListener("click", () => {
    $("email").value = b.dataset.e; $("pw").value = "demo1234"; $("pw").focus();
  }));
  $("f").addEventListener("submit", async function (ev) {
    ev.preventDefault();
    $("err").hidden = true;
    try {
      const me = await LM.login($("email").value.trim(), $("pw").value);
      location.href = me.home;
    } catch (e) {
      $("err").hidden = false;
      $("err").textContent = e.kind === "network" ? "No connection. Try again." : "Wrong email or password.";
    }
  });
})();
