/* OPEN LATE app shell: one top bar on every page, one sheet, one short-wait bar.
 *
 *   <link rel="stylesheet" href="/static/tokens.css">
 *   <header id="ol-shell" data-page="fitting"></header>
 *   <script src="/static/shell.js"></script>     right after the header, so the bar paints with the page
 *
 * data-ops on the header shows render engine status (internal pages only).
 *
 *   OL.wait(promise)         thin bar under the top bar if the promise takes over a second
 *   OL.sheet(title, node)    side sheet on desktop, bottom sheet on a phone; the back button closes it
 *   OL.sizeChart(element)    embed the size chart;  OL.setSize("M") highlights a size
 */
(() => {
  const css = `
  .ol-shell{position:relative;z-index:30;height:var(--shell);display:flex;align-items:center;gap:16px;padding:0 16px;background:var(--panel);
    border-bottom:1px solid var(--line);color:var(--t1);font-size:14px;line-height:1.4}
  .ol-shell *{box-sizing:border-box}
  .ol-shell .b{font-weight:800;letter-spacing:.14em;font-size:13px;color:var(--t1);text-decoration:none;flex:none;white-space:nowrap}
  .ol-shell nav{display:flex;gap:2px;overflow-x:auto;scrollbar-width:none;flex:1;min-width:0}
  .ol-shell nav a{color:var(--t3);text-decoration:none;padding:6px 10px;border-radius:7px;white-space:nowrap}
  .ol-shell nav a:hover{color:var(--t1);background:var(--hover)}
  .ol-shell nav a[aria-current=page]{color:var(--t1);font-weight:600}
  .ol-shell .eng{margin-left:auto;display:flex;align-items:center;gap:10px;flex:none;color:var(--t3);font-size:13px;white-space:nowrap}
  .ol-shell .eng b{color:var(--t1);font-weight:600;font-variant-numeric:tabular-nums}
  .ol-shell .led{width:7px;height:7px;border-radius:50%;background:var(--t4)}
  .ol-shell .led.on{background:var(--ok)}
  @media(max-width:1100px){.ol-shell .eng .opt{display:none}}
  @media(max-width:760px){.ol-shell .eng{display:none}.ol-shell{gap:8px;padding:0 10px}.ol-shell nav a{padding:6px 7px}}
  .ol-sheet{position:fixed;top:0;right:0;bottom:0;width:min(460px,100vw);z-index:60;background:var(--panel);color:var(--t1);
    border-left:1px solid var(--line);box-shadow:var(--shadow);transform:translateX(100%);visibility:hidden;transition:transform .2s ease,visibility .2s;
    display:flex;flex-direction:column}
  .ol-sheet.on{transform:none;visibility:visible}
  @media(max-width:760px){.ol-sheet{top:auto;left:0;width:100%;max-height:88vh;border-left:0;border-radius:14px 14px 0 0;transform:translateY(100%)}}
  .ol-sheet header{display:flex;align-items:center;padding:12px 16px;border-bottom:1px solid var(--line)}
  .ol-sheet header h2{margin:0;font-size:16px;font-weight:650}
  .ol-sheet header button{margin-left:auto;width:44px;height:44px;margin-right:-10px;background:none;border:0;color:var(--t3);cursor:pointer;font-size:17px}
  .ol-sheet .body{padding:14px 16px 20px;overflow:auto}
  .ol-chart{width:100%;border-collapse:collapse;font-variant-numeric:tabular-nums;font-size:14px}
  .ol-chart th,.ol-chart td{padding:7px 6px;text-align:right;border-bottom:1px solid var(--line)}
  .ol-chart th:first-child,.ol-chart td:first-child{text-align:left;color:var(--t3);font-weight:500;white-space:nowrap}
  .ol-chart thead th{font-weight:650}
  .ol-chart .grp td{color:var(--t3);font-size:13px;padding-top:12px;border-bottom:0}
  .ol-chart .hl{background:var(--chip);color:var(--t1);font-weight:650}
  .ol-chart .grp td.hl{background:none}
  .ol-note{color:var(--t3);font-size:13px;margin:10px 0 0}
  .ol-scrim{position:fixed;inset:0;z-index:55;background:rgba(0,0,0,.3);opacity:0;pointer-events:none;transition:opacity .2s}
  .ol-scrim.on{opacity:1;pointer-events:auto}
  @media (prefers-reduced-motion:reduce){.ol-sheet,.ol-scrim{transition:none}}`;
  const style = document.createElement("style"); style.textContent = css; document.head.append(style);

  const NAV = [["/", "pipeline", "Pipeline"], ["/fitting", "fitting", "Fitting room"], ["/fitting/qa", "fit-qa", "Fit QA"],
               ["/colorways/", "colorways", "Colorways"], ["/review/", "review", "Review"]];
  const host = document.getElementById("ol-shell");
  if (!host) return;
  host.className = "ol-shell";
  host.innerHTML = `
    <a class="b" href="/">OPEN LATE</a>
    <nav aria-label="Pages">${NAV.map(([href, key, label]) =>
      `<a href="${href}" ${key === host.dataset.page ? 'aria-current="page"' : ""}>${label}</a>`).join("")}</nav>
    ${"ops" in host.dataset ? '<span class="eng" id="ol-eng" aria-live="polite"></span>' : ""}`;

  // short waits
  const bar = document.createElement("div"); bar.className = "ol-bar"; bar.innerHTML = "<i></i>";
  let waiting = 0, timer = null;
  const wait = p => {
    waiting++;
    timer ??= setTimeout(() => bar.classList.add("on"), 1000);
    return Promise.resolve(p).finally(() => { if (--waiting === 0) { clearTimeout(timer); timer = null; bar.classList.remove("on"); } });
  };

  // engine status, internal pages only
  const eng = host.querySelector("#ol-eng");
  async function engine() {
    try {
      const e = await (await fetch("/api/engine")).json(), a = e.averages || {};
      const m = e.models || {}, sec = k => (a[k] ? `${a[k].avg} s` : "—");
      eng.innerHTML = e.online
        ? `<span class="led on"></span>
           <span title="Model photo, average per image">Photo <b>${m.portrait || ""}</b> <b>${sec("portrait")}</b></span>
           <span class="opt" title="Try-on, average per garment">Try-on <b>${m.tryon || ""}</b> <b>${sec("tryon")}</b></span>
           ${e.queue ? `<span>Queue <b>${e.queue}</b></span>` : ""}`
        : `<span class="led"></span>Render engine off`;
    } catch (e) { eng.textContent = ""; }
  }
  if (eng) { engine(); setInterval(engine, 10000); }

  // one sheet, opened by the page or by the size chart
  const sheet = document.createElement("aside");
  sheet.className = "ol-sheet"; sheet.setAttribute("role", "dialog"); sheet.setAttribute("aria-modal", "true");
  sheet.innerHTML = `<header><h2></h2><button type="button" aria-label="Close">✕</button></header><div class="body"></div>`;
  const scrim = document.createElement("div"); scrim.className = "ol-scrim";
  document.addEventListener("DOMContentLoaded", () => document.body.append(bar, scrim, sheet));
  const heading = sheet.querySelector("h2"), body = sheet.querySelector(".body");
  let open = false, back = null;
  const hide = () => { open = false; sheet.classList.remove("on"); scrim.classList.remove("on"); if (back) back.focus(); };
  const close = () => { if (open) history.back(); };
  function show(title, ...nodes) {
    heading.textContent = title; sheet.setAttribute("aria-label", title); body.replaceChildren(...nodes);
    if (!open) { back = document.activeElement; open = true; history.pushState({olSheet: 1}, ""); }
    sheet.classList.add("on"); scrim.classList.add("on"); sheet.querySelector("header button").focus();
  }
  window.addEventListener("popstate", () => { if (open) hide(); });
  sheet.querySelector("header button").addEventListener("click", close);
  scrim.addEventListener("click", close);
  document.addEventListener("keydown", e => { if (e.key === "Escape") close(); });

  // size chart
  let chart = null, size = null;
  const inlines = new Set();
  async function loadChart() {
    if (!chart) { try { chart = await (await fetch("/api/sizechart")).json(); } catch (e) { chart = null; } }
    return chart;
  }
  function table(c) {
    if (!c || !c.sizes) return "<p class=ol-note>The size chart could not be loaded.</p>";
    const col = s => (s === size ? ' class="hl"' : "");
    const row = (label, f) => `<tr><td>${label}</td>${c.sizes.map(s => `<td${col(s)}>${f(s) ?? "—"}</td>`).join("")}</tr>`;
    const g = c.garment, w = c.wearer;
    return `<table class="ol-chart"><thead><tr><th>cm</th>${c.sizes.map(s => `<th${col(s)}>${s}</th>`).join("")}</tr></thead><tbody>
      <tr class="grp"><td colspan="${c.sizes.length + 1}">Finished garment · ${c.design}</td></tr>
      ${row("Chest around", s => g[s]?.chest)}${row("Length", s => g[s]?.length)}${row("Sleeve", s => g[s]?.sleeve)}
      <tr class="grp"><td colspan="${c.sizes.length + 1}">Bodies this size is drafted for</td></tr>
      ${row("Height, men", s => w.male[s]?.height)}${row("Height, women", s => w.female[s]?.height)}
      ${row("Chest, men", s => w.male[s]?.chest)}${row("Chest, women", s => w.female[s]?.chest)}
      </tbody></table>`;
  }
  async function paint() {
    const c = await loadChart();
    for (const el of inlines) el.innerHTML = table(c) + (c && c.note ? `<p class="ol-note">${c.note}</p>` : "");
  }

  window.OL = {
    wait,
    sheet: show,
    closeSheet: close,
    async openChart() { const box = document.createElement("div"); const c = await wait(loadChart());
      box.innerHTML = table(c) + (c && c.note ? `<p class="ol-note">${c.note}</p>` : ""); show("Size chart", box); },
    sizeChart(el) { inlines.add(el); paint(); },
    setSize(s) { if (s !== size) { size = s; paint(); } },
    refreshChart() { chart = null; paint(); },
  };
})();
