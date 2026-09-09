"use strict";
(() => {
  const toggle = document.getElementById("nav-toggle");
  const backdrop = document.getElementById("nav-backdrop");
  function close() { document.body.classList.remove("nav-open"); toggle?.setAttribute("aria-expanded", "false"); if (backdrop) backdrop.hidden = true; }
  toggle?.addEventListener("click", () => { const open = document.body.classList.toggle("nav-open"); toggle.setAttribute("aria-expanded", String(open)); backdrop.hidden = !open; });
  backdrop?.addEventListener("click", close);
  document.addEventListener("keydown", event => { if (event.key === "Escape") { close(); document.querySelectorAll(".account-menu[open]").forEach(menu => { menu.open = false; }); } });
  window.addEventListener("pageshow", () => {
    // Do not restore private assistant content from back/forward navigation caches.
    const history = document.getElementById("copilot-history");
    if (history) history.replaceChildren();
  });
})();
