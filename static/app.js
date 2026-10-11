(function () {
  const toast = document.getElementById("toast");
  let toastTimer;
  function showToast(msg) {
    toast.textContent = msg;
    toast.classList.add("show");
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => toast.classList.remove("show"), 2600);
  }

  // "How to paste into EVE" pop-up, shown after copying a fit
  const howto = document.getElementById("howto");
  const SKIP_KEY = "rw-hide-howto";
  function howtoHidden() {
    try { return localStorage.getItem(SKIP_KEY) === "1"; } catch (e) { return false; }
  }
  function showHowto(fitName) {
    if (!howto || typeof howto.showModal !== "function" || howtoHidden()) return false;
    document.getElementById("howto-fit").textContent = fitName || "";
    document.getElementById("howto-skip").checked = false;
    howto.showModal();
    return true;
  }
  if (howto) {
    howto.addEventListener("close", () => {
      if (document.getElementById("howto-skip").checked) {
        try { localStorage.setItem(SKIP_KEY, "1"); } catch (e) { /* private mode */ }
      }
    });
    // click outside the box closes it
    howto.addEventListener("click", (e) => { if (e.target === howto) howto.close(); });
  }

  async function copyText(text) {
    if (navigator.clipboard && window.isSecureContext) {
      try { await navigator.clipboard.writeText(text); return true; } catch (e) { /* fall through */ }
    }
    const ta = document.createElement("textarea");
    ta.value = text;
    ta.style.position = "fixed";
    ta.style.opacity = "0";
    document.body.appendChild(ta);
    ta.select();
    let ok = false;
    try { ok = document.execCommand("copy"); } catch (e) { ok = false; }
    ta.remove();
    return ok;
  }

  document.addEventListener("click", async (e) => {
    const btn = e.target.closest(".copy-btn");
    if (!btn) return;
    const src = document.getElementById(btn.dataset.copy);
    if (!src) return;
    const ok = await copyText(src.value);
    if (ok) {
      const label = btn.textContent;
      btn.classList.add("copied");
      btn.textContent = "Copied!";
      const popped = btn.dataset.howto === "fit" && showHowto(btn.dataset.fitname);
      if (!popped) showToast(btn.dataset.toast || "Fit copied. In EVE: Fitting window > Import & Export > Import from Clipboard");
      setTimeout(() => { btn.classList.remove("copied"); btn.textContent = label; }, 1800);
    } else {
      showToast("Couldn't copy automatically. Open Module list and copy the text by hand.");
    }
  });

  // Fit card tabs: Fit / Required skills / Module list
  document.addEventListener("click", (e) => {
    const tab = e.target.closest(".tab[data-tab]");
    if (!tab) return;
    const card = tab.closest(".fit");
    card.querySelectorAll(".tab").forEach((t) => {
      const on = t === tab;
      t.classList.toggle("active", on);
      t.setAttribute("aria-selected", on ? "true" : "false");
      const panel = document.getElementById(t.dataset.tab);
      if (panel) panel.hidden = !on;
    });
  });

  // Tap a module tile on touch screens to see its name
  document.addEventListener("click", (e) => {
    const tile = e.target.closest(".tile[data-name]");
    if (tile && window.matchMedia("(hover: none)").matches) showToast(tile.dataset.name);
  });
})();
