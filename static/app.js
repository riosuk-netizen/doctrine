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

  // Fitting skill boxes: clicking the level that's already set clears it
  document.addEventListener("pointerdown", (e) => {
    const box = e.target.closest(".fs-box");
    if (!box) return;
    const input = document.getElementById(box.htmlFor);
    box.dataset.wasChecked = input && input.checked ? "1" : "";
  });
  document.addEventListener("click", (e) => {
    const box = e.target.closest(".fs-box");
    if (!box || box.dataset.wasChecked !== "1") return;
    e.preventDefault();
    box.dataset.wasChecked = "";
    const zero = box.closest(".fs-boxes").querySelector(".fs-zero");
    if (zero) zero.checked = true;
  });

  // Front page search: ships, fits, doctrines, roles, modules, authors
  const searchBox = document.getElementById("search");
  const searchData = document.getElementById("search-data");
  if (searchBox && searchData) {
    const data = JSON.parse(searchData.textContent);
    const results = document.getElementById("search-results");
    const grid = document.getElementById("doctrine-grid");
    const esc = (s) => String(s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
    const hl = (text, words) => {
      let out = esc(text);
      words.forEach((w) => {
        const re = new RegExp("(" + esc(w).replace(/[.*+?^${}()|[\]\\]/g, "\\$&") + ")", "ig");
        out = out.replace(re, "<mark>$1</mark>");
      });
      return out;
    };
    const fitFields = (f) => [
      ["", f.fit], ["", f.ship], ["Class", f.cls], ["Doctrine", f.doctrine],
      ...f.roles.map((r) => ["Role", r]), ["By", f.author], ...f.modules.map((m) => ["Fitted", m]),
    ];
    function run() {
      const q = searchBox.value.trim().toLowerCase();
      if (!q) { results.hidden = true; results.innerHTML = ""; grid.hidden = false; return; }
      const words = q.split(/\s+/).filter(Boolean);
      const fits = [];
      data.fits.forEach((f) => {
        const fields = fitFields(f).filter(([, v]) => v);
        const hay = fields.map(([, v]) => v.toLowerCase()).join(" \u0001 ");
        if (!words.every((w) => hay.includes(w))) return;
        // the first match outside the name / ship line explains why it showed up
        const why = fields.find(([k, v]) => k && k !== "Doctrine" && k !== "Class" && words.some((w) => v.toLowerCase().includes(w)));
        const score = words.reduce((n, w) => n + (f.fit.toLowerCase().includes(w) || f.ship.toLowerCase().includes(w) ? 2 : 1), 0);
        fits.push({ f, why, score });
      });
      fits.sort((a, b) => b.score - a.score);
      const docs = data.doctrines.filter((d) => {
        const hay = [d.name, d.author, d.desc].join(" ").toLowerCase();
        return words.every((w) => hay.includes(w));
      });
      grid.hidden = true;
      results.hidden = false;
      if (!fits.length && !docs.length) {
        results.innerHTML = '<div class="sr-empty">Nothing found for <strong>' + esc(searchBox.value.trim()) + "</strong>. Try a ship name, a role like tackle, or a module.</div>";
        return;
      }
      let html = '<p class="sr-head">' + fits.length + " fit" + (fits.length === 1 ? "" : "s") +
        (docs.length ? " and " + docs.length + " doctrine" + (docs.length === 1 ? "" : "s") : "") + "</p>";
      if (fits.length) {
        html += '<div class="sr-section"><h3>Fits</h3><div class="sr-list">' + fits.map(({ f, why }) => {
          const mark = data.meta[f.meta] ? '<span class="meta-mark m' + f.meta + '" aria-hidden="true"></span>' : "";
          const icon = f.icon ? '<span class="hull-thumb"><img src="' + esc(f.icon) + '" alt="" loading="lazy">' + mark + "</span>" : "";
          return '<a class="sr-item" href="' + esc(f.url) + '">' + icon + '<span class="sr-text">' +
            '<span class="sr-title">' + hl(f.fit, words) + "</span>" +
            '<span class="sr-sub">' + hl(f.ship, words) + (f.cls ? " · " + hl(f.cls, words) : "") + " · " + hl(f.doctrine, words) + "</span>" +
            (why ? '<span class="sr-why">' + esc(why[0]) + ": " + hl(why[1], words) + "</span>" : "") +
            "</span></a>";
        }).join("") + "</div></div>";
      }
      if (docs.length) {
        html += '<div class="sr-section"><h3>Doctrines</h3><div class="sr-list">' + docs.map((d) =>
          '<a class="sr-item" href="' + esc(d.url) + '"><span class="sr-text"><span class="sr-title">' + hl(d.name, words) + "</span>" +
          '<span class="sr-sub">' + d.fits + " fit" + (d.fits === 1 ? "" : "s") + (d.author ? " · by " + hl(d.author, words) : "") + "</span></span></a>"
        ).join("") + "</div></div>";
      }
      results.innerHTML = html;
    }
    searchBox.addEventListener("input", run);
    searchBox.addEventListener("keydown", (e) => {
      if (e.key === "Escape") { searchBox.value = ""; run(); }
      if (e.key === "Enter") { const first = results.querySelector(".sr-item"); if (first) first.click(); }
    });
    document.addEventListener("keydown", (e) => {
      if (e.key === "/" && document.activeElement !== searchBox && !/input|textarea/i.test(document.activeElement.tagName)) {
        e.preventDefault(); searchBox.focus();
      }
    });
    if (searchBox.value) run();
  }

  // Tap a module tile on touch screens to see its name
  document.addEventListener("click", (e) => {
    const tile = e.target.closest(".tile[data-name]");
    if (tile && window.matchMedia("(hover: none)").matches) showToast(tile.dataset.name);
  });
})();
