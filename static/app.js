(function () {
  const toast = document.getElementById("toast");
  let toastTimer;
  function showToast(msg) {
    toast.textContent = msg;
    toast.classList.add("show");
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => toast.classList.remove("show"), 2600);
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
      showToast("Fit copied. In EVE: Fitting window > Import & Export > Import from Clipboard");
      setTimeout(() => { btn.classList.remove("copied"); btn.textContent = label; }, 1800);
    } else {
      showToast("Couldn't copy automatically. Open Module list and copy the text by hand.");
    }
  });

  // Tap a module tile on touch screens to see its name
  document.addEventListener("click", (e) => {
    const tile = e.target.closest(".tile[data-name]");
    if (tile && window.matchMedia("(hover: none)").matches) showToast(tile.dataset.name);
  });
})();
