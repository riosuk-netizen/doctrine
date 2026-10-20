(function () {
  const toast = document.getElementById("toast");
  let toastTimer;
  function showToast(msg) {
    toast.textContent = msg;
    toast.classList.add("show");
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => toast.classList.remove("show"), Math.max(2600, msg.length * 55));
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
    const flyBtn = document.getElementById("fly-toggle");
    const FLY_KEY = "rw-only-fly";
    let onlyFly = false;
    if (flyBtn) {
      try { onlyFly = localStorage.getItem(FLY_KEY) === "1"; } catch (e) { /* private mode */ }
      const paint = () => { flyBtn.setAttribute("aria-pressed", onlyFly ? "true" : "false"); flyBtn.classList.toggle("on", onlyFly); };
      paint();
      flyBtn.addEventListener("click", () => {
        onlyFly = !onlyFly;
        try { localStorage.setItem(FLY_KEY, onlyFly ? "1" : "0"); } catch (e) { /* private mode */ }
        paint();
        run();
      });
    }
    // editors: private doctrines are hidden until "Show private doctrines" is ticked
    const privBtn = document.getElementById("private-toggle");
    const PRIV_KEY = "rw-show-private";
    let showPrivate = false;
    if (privBtn) {
      try { showPrivate = localStorage.getItem(PRIV_KEY) === "1"; } catch (e) { /* private mode */ }
      const paintPriv = () => {
        privBtn.setAttribute("aria-pressed", showPrivate ? "true" : "false");
        privBtn.classList.toggle("on", showPrivate);
        grid.classList.toggle("show-private", showPrivate);
      };
      paintPriv();
      privBtn.addEventListener("click", () => {
        showPrivate = !showPrivate;
        try { localStorage.setItem(PRIV_KEY, showPrivate ? "1" : "0"); } catch (e) { /* private mode */ }
        paintPriv();
        run();
      });
    }
    const flyTag = { ready: '<span class="sr-fly ready">&#10003; Can fly</span>', short: '<span class="sr-fly short">Missing skills</span>', clone: '<span class="sr-fly clone">Needs Omega</span>' };
    function run() {
      const q = searchBox.value.trim().toLowerCase();
      if (!q && !onlyFly) { results.hidden = true; results.innerHTML = ""; grid.hidden = false; return; }
      const words = q.split(/\s+/).filter(Boolean);
      const fits = [];
      data.fits.forEach((f) => {
        if (onlyFly && f.fly !== "ready") return;
        if (f.private && !showPrivate) return;
        const fields = fitFields(f).filter(([, v]) => v);
        const hay = fields.map(([, v]) => v.toLowerCase()).join(" \u0001 ");
        if (!words.every((w) => hay.includes(w))) return;
        // the first match outside the name / ship line explains why it showed up
        const why = fields.find(([k, v]) => k && k !== "Doctrine" && k !== "Class" && words.some((w) => v.toLowerCase().includes(w)));
        const score = words.reduce((n, w) => n + (f.fit.toLowerCase().includes(w) || f.ship.toLowerCase().includes(w) ? 2 : 1), 0);
        fits.push({ f, why, score });
      });
      fits.sort((a, b) => b.score - a.score);
      const docs = onlyFly ? [] : data.doctrines.filter((d) => {
        if (d.private && !showPrivate) return false;
        const hay = [d.name, d.author, d.desc].join(" ").toLowerCase();
        return words.every((w) => hay.includes(w));
      });
      grid.hidden = true;
      results.hidden = false;
      if (!fits.length && !docs.length) {
        results.innerHTML = onlyFly
          ? '<div class="sr-empty">' + (q ? "None of the fits matching <strong>" + esc(searchBox.value.trim()) + "</strong> are ready for you yet." : "You can't fly any of the fits yet.") + " Turn off <strong>Only show fits I can fly</strong> to see what you're missing.</div>"
          : '<div class="sr-empty">Nothing found for <strong>' + esc(searchBox.value.trim()) + "</strong>. Try a ship name, a role like tackle, or a module.</div>";
        return;
      }
      let html = '<p class="sr-head">' + fits.length + " fit" + (fits.length === 1 ? "" : "s") + (onlyFly ? " you can fly" : "") +
        (docs.length ? " and " + docs.length + " doctrine" + (docs.length === 1 ? "" : "s") : "") + "</p>";
      if (fits.length) {
        html += '<div class="sr-section"><h3>Fits</h3><div class="sr-list">' + fits.map(({ f, why }) => {
          const mark = data.meta[f.meta] ? '<span class="meta-mark m' + f.meta + '" aria-hidden="true"></span>' : "";
          const icon = f.icon ? '<span class="hull-thumb"><img src="' + esc(f.icon) + '" alt="" loading="lazy">' + mark + "</span>" : "";
          return '<a class="sr-item" href="' + esc(f.url) + '">' + icon + '<span class="sr-text">' +
            '<span class="sr-title">' + hl(f.fit, words) + (f.fly && flyTag[f.fly] ? " " + flyTag[f.fly] : "") + "</span>" +
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
    if (searchBox.value || onlyFly) run();
  }

  // Push to EVE: sends the fit (or the whole doctrine) to the logged-in character's fittings
  document.addEventListener("click", async (e) => {
    const btn = e.target.closest(".save-eve");
    if (!btn || btn.disabled) return;
    if (btn.dataset.login) { window.location.href = btn.dataset.login; return; }
    if (btn.dataset.confirm && !window.confirm(btn.dataset.confirm)) return;
    const label = btn.textContent;
    btn.disabled = true;
    btn.textContent = "Pushing...";
    let res = null;
    try {
      const r = await fetch(btn.dataset.url, { method: "POST", headers: { "X-Requested-With": "fetch" } });
      res = await r.json();
    } catch (err) {
      res = { ok: false, message: "Couldn't reach the site. Check your connection and try again." };
    }
    btn.disabled = false;
    if (res.login && !res.saved) {
      showToast(res.message + " Taking you to the EVE login...");
      setTimeout(() => { window.location.href = "/sso/login?next=" + encodeURIComponent(location.pathname + location.hash); }, 1400);
      btn.textContent = label;
      return;
    }
    showToast(res.message);
    if (res.ok) {
      btn.classList.add("copied");
      btn.textContent = "Pushed!";
      setTimeout(() => { btn.classList.remove("copied"); btn.textContent = label; }, 2200);
    } else {
      btn.textContent = label;
    }
  });

  // Skill descriptions: place the box next to the skill name, flipping above it near the bottom of the screen
  function placeTip(name) {
    const tip = name.querySelector(".skill-tip");
    if (!tip) return;
    const r = name.getBoundingClientRect();
    tip.style.visibility = "hidden";
    tip.style.display = "block";
    const w = tip.offsetWidth, h = tip.offsetHeight;
    tip.style.display = "";
    tip.style.visibility = "";
    const left = Math.max(8, Math.min(r.left, window.innerWidth - w - 8));
    const below = r.bottom + 6;
    const top = below + h > window.innerHeight - 8 && r.top - h - 6 > 8 ? r.top - h - 6 : below;
    tip.style.left = left + "px";
    tip.style.top = top + "px";
  }
  ["mouseover", "focusin"].forEach((ev) => document.addEventListener(ev, (e) => {
    const name = e.target.closest && e.target.closest(".skill-name.has-tip");
    if (name && !name.contains(e.relatedTarget)) placeTip(name);
  }));
  window.addEventListener("scroll", () => {
    document.querySelectorAll(".skill-name.show").forEach((n) => n.classList.remove("show"));
    const hovered = document.querySelector(".skill-name.has-tip:hover");
    if (hovered) placeTip(hovered);
  }, { passive: true });

  // Skill descriptions: tap a skill name on touch screens to open or close it
  document.addEventListener("click", (e) => {
    const name = e.target.closest(".skill-name.has-tip");
    document.querySelectorAll(".skill-name.show").forEach((n) => { if (n !== name) n.classList.remove("show"); });
    if (name && window.matchMedia("(hover: none)").matches) { placeTip(name); name.classList.toggle("show"); }
  });

  // Visibility switch on a doctrine page saves as soon as it's changed
  document.addEventListener("change", (e) => {
    const form = e.target.closest("form.auto-submit");
    if (form) form.submit();
    // Copy to: show the name box only when copying into a new doctrine
    if (e.target.classList.contains("copy-target")) {
      const box = e.target.closest("form").querySelector(".copy-new");
      box.hidden = e.target.value !== "new";
      if (!box.hidden) box.querySelector("input").focus();
    }
  });
  // close an open Copy to box when clicking elsewhere
  document.addEventListener("click", (e) => {
    document.querySelectorAll("details.copy-to[open]").forEach((dt) => { if (!dt.contains(e.target)) dt.open = false; });
  });

  // Role tag buttons: click to add or remove a tag in the box just before them
  const tagsOf = (input) => input.value.split(",").map((t) => t.trim()).filter(Boolean);
  const roleInput = (picker) => picker.previousElementSibling;
  function paintRoles(picker) {
    const input = roleInput(picker);
    if (!input) return;
    const have = tagsOf(input).map((t) => t.toLowerCase());
    picker.querySelectorAll(".role-chip").forEach((b) => {
      const on = have.includes(b.dataset.role.toLowerCase());
      b.classList.toggle("on", on);
      b.setAttribute("aria-pressed", on ? "true" : "false");
    });
  }
  document.querySelectorAll(".role-picker").forEach(paintRoles);
  document.addEventListener("input", (e) => {
    const next = e.target.nextElementSibling;
    if (next && next.classList.contains("role-picker")) paintRoles(next);
  });
  document.addEventListener("click", (e) => {
    const b = e.target.closest(".role-chip");
    if (!b) return;
    e.preventDefault();
    const picker = b.closest(".role-picker"), input = roleInput(picker);
    const tags = tagsOf(input);
    const i = tags.findIndex((t) => t.toLowerCase() === b.dataset.role.toLowerCase());
    if (i >= 0) tags.splice(i, 1); else tags.push(b.dataset.role);
    input.value = tags.join(", ");
    paintRoles(picker);
  });

  // Doctrine form: one box per fit, with Add another fit and remove buttons
  const blocks = document.getElementById("fit-blocks");
  const tpl = document.getElementById("fit-block-template");
  function renumber() {
    const all = blocks.querySelectorAll(".fit-block");
    all.forEach((bl, i) => {
      bl.querySelector(".fit-block-title").textContent = "Fit " + (i + 1);
      bl.querySelector(".fit-block-remove").hidden = all.length === 1;
    });
  }
  if (blocks && tpl) {
    renumber();
    document.getElementById("add-fit-block").addEventListener("click", () => {
      blocks.appendChild(tpl.content.cloneNode(true));
      renumber();
      const added = blocks.lastElementChild;
      paintRoles(added.querySelector(".role-picker"));
      added.querySelector("textarea").focus();
    });
    blocks.addEventListener("click", (e) => {
      const rm = e.target.closest(".fit-block-remove");
      if (!rm) return;
      const bl = rm.closest(".fit-block");
      if (bl.querySelector("textarea").value.trim() && !window.confirm("Remove this fit from the form?")) return;
      bl.remove();
      renumber();
    });
  }

  // Tap a module tile on touch screens to see its name
  document.addEventListener("click", (e) => {
    const tile = e.target.closest(".tile[data-name]");
    if (tile && window.matchMedia("(hover: none)").matches) showToast(tile.dataset.name);
  });
})();
