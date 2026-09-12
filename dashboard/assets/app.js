/* JobBot shell — Opportunity Intelligence System (session 13).
   Injects: skip link, the mission rail (left), the utility rail (top) with
   the notification bell, and the notification drawer. Pages own <main>.
   All DB-sourced text renders through esc()/textContent — postings and email
   text are untrusted end to end.

   Notifications: one center, zero banners. needs_you items persist until the
   condition resolves server-side; read-state lives in SQLite via
   POST /api/notifs/seen (never faked in localStorage). The only localStorage
   here is the rail-collapse device preference. */

"use strict";

const NAV = [
  { grp: "Operate" },
  { path: "/", page: "overview", label: "Overview", alias: "Mission Control", glyph: "◉" },
  { path: "/queue", page: "queue", label: "Queue", alias: "Intervention Bay", glyph: "⌁", badge: "queue" },
  { path: "/inbox", page: "inbox", label: "Inbox", alias: "Signal Intelligence", glyph: "◍" },
  { grp: "Records" },
  { path: "/applications", page: "applications", label: "Applications", alias: "Opportunity Pipeline", glyph: "⌗" },
  { path: "/submissions", page: "submissions", label: "Submissions", alias: "Secure Egress", glyph: "⇗" },
  { path: "/answers", page: "answers", label: "Answers", alias: "Knowledge Vault", glyph: "✎", badge: "gaps" },
  { grp: "System" },
  { path: "/agent", page: "agent", label: "Agents", alias: "Network Operations", glyph: "λ" },
  { path: "/chat", page: "chat", label: "Chat", alias: "Operator Console", glyph: "»" },
];

function esc(s) {
  return String(s ?? "").replace(/[&<>"']/g, c => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  }[c]));
}

async function fetchJSON(url, opts) {
  const r = await fetch(url, opts);
  const data = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(data.error || `${r.status} on ${url}`);
  return data;
}

const post = (url, body) => fetchJSON(url, {
  method: "POST",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify(body || {}),
});

const qparam = name => new URLSearchParams(location.search).get(name) || "";

/* job-source display names (raw value stays in the tooltip) */
const SRC_LABEL = {
  company_page: "Company site", linkedin: "LinkedIn", linkedin_alert: "LinkedIn",
  indeed_alert: "Indeed", ziprecruiter_alert: "ZipRecruiter",
  glassdoor_alert: "Glassdoor", adzuna: "Adzuna", usajobs: "USAJobs",
  inbox: "Email alert", jobright_alert: "Jobright", manual: "Manual", seed: "Seed",
};
const srcLabel = s => SRC_LABEL[s] || String(s || "—").replace(/_/g, " ");
const srcPill = s => `<span class="pill" title="source: ${esc(s)}">${esc(srcLabel(s))}</span>`;

/* ---- formatting (times always AM/PM — operator rule) ------------------- */

function ampm(hhmm) {
  const [h, m] = hhmm.split(":").map(Number);
  const ap = h >= 12 ? "PM" : "AM";
  return `${h % 12 || 12}:${String(m).padStart(2, "0")} ${ap}`;
}

const fmt = {
  money: n => "$" + (+n).toFixed(2),
  money4: n => "$" + (+n).toFixed(4),
  int: n => (+n || 0).toLocaleString("en-US"),
  tokens: n => n >= 1e6 ? (n / 1e6).toFixed(1) + "M"
    : n >= 1000 ? (n / 1000).toFixed(1) + "k" : String(n ?? 0),
  ms: n => n == null ? "—" : n < 1000 ? n + "ms"
    : n < 60000 ? (n / 1000).toFixed(1) + "s"
    : Math.floor(n / 60000) + "m" + String(Math.round(n % 60000 / 1000)).padStart(2, "0") + "s",
  ts: t => {
    if (!t) return "—";
    const d = new Date();
    const today = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
    const time = ampm(t.slice(11, 16));
    return t.slice(0, 10) === today ? time : `${t.slice(5, 10)} · ${time}`;
  },
  date: t => (t || "").slice(0, 10) || "—",
  clock: d => {
    const h = d.getHours(), ap = h >= 12 ? "PM" : "AM";
    return `${h % 12 || 12}:${String(d.getMinutes()).padStart(2, "0")}:${String(d.getSeconds()).padStart(2, "0")} ${ap}`;
  },
};

/* Clipboard: the dashboard is plain http (not a secure context) — execCommand fallback. */
function copyText(text, el) {
  let ok = false;
  try {
    const ta = document.createElement("textarea");
    ta.value = text;
    ta.style.position = "fixed";
    ta.style.opacity = "0";
    document.body.appendChild(ta);
    ta.select();
    ok = document.execCommand("copy");
    ta.remove();
  } catch (e) { ok = false; }
  if (el) {
    const prev = el.textContent;
    el.classList.add("copied");
    el.textContent = ok ? "Copied ✓" : "Copy failed";
    setTimeout(() => { el.classList.remove("copied"); el.textContent = prev; }, 1200);
  }
  return ok;
}

/* ---- skeletons / flash ------------------------------------------------- */

function skelRows(el, cols, n = 5) {
  el.innerHTML = Array.from({ length: n }, () =>
    `<tr>${Array.from({ length: cols }, () => `<td><div class="skel"></div></td>`).join("")}</tr>`).join("");
}
function skelTiles(el, n = 6) {
  el.innerHTML = Array.from({ length: n }, () => `<div class="skel skel-tile"></div>`).join("");
}
function skelCards(el, n = 3) {
  el.innerHTML = Array.from({ length: n }, () => `<div class="skel skel-card"></div>`).join("");
}
function flashEl(el) {
  if (!el) return;
  el.scrollIntoView({ behavior: "smooth", block: "center" });
  el.classList.remove("flash");
  void el.offsetWidth;
  el.classList.add("flash");
}

/* ---- shell construction ------------------------------------------------ */

const RAIL_PREF = "jb-rail-min";           // device preference only

function buildRail(active) {
  const rail = document.createElement("nav");
  rail.id = "rail";
  rail.setAttribute("aria-label", "Mission rail");
  let html = `<div class="brand"><span class="sigil" aria-hidden="true">◇</span>
    <span class="nm">JOBBOT<small>OPPORTUNITY INTELLIGENCE</small></span></div>
    <button class="ghost" id="rail-toggle" aria-label="Collapse navigation" title="Collapse or expand navigation">⟨</button>`;
  for (const it of NAV) {
    if (it.grp) { html += `<div class="grp microcap">${it.grp}</div>`; continue; }
    html += `<a class="item ${it.page === active ? "active" : ""}" href="${it.path}"
        ${it.page === active ? 'aria-current="page"' : ""} title="${it.label} — ${it.alias}">
      <span class="glyph" aria-hidden="true">${it.glyph}</span>
      <span class="lbl"><b>${it.label}</b><small>${it.alias}</small></span>
      ${it.badge ? `<span class="badge ${it.badge === "gaps" ? "amber" : ""}" id="badge-${it.badge}"></span>` : ""}
    </a>`;
  }
  html += `<div class="foot"><span class="clock" id="nav-clock"></span>
    <span id="nav-next"></span><br>SOC console · CT 200</div>`;
  rail.innerHTML = html;
  document.body.prepend(rail);

  const clock = document.getElementById("nav-clock");
  const tick = () => { clock.textContent = fmt.clock(new Date()); };
  tick();
  setInterval(tick, 1000);

  const tog = document.getElementById("rail-toggle");
  const paintTog = () => { tog.textContent = document.body.classList.contains("rail-min") ? "⟩" : "⟨"; };
  paintTog();
  tog.onclick = () => {
    const min = document.body.classList.toggle("rail-min");
    try { localStorage.setItem(RAIL_PREF, min ? "1" : ""); } catch (e) {}
    paintTog();
    requestAnimationFrame(() => window.dispatchEvent(new Event("resize")));
  };
}

function buildTopbar(active) {
  const it = NAV.find(n => n.page === active) || NAV[1];
  const bar = document.createElement("header");
  bar.id = "topbar";
  bar.innerHTML = `
    <button class="small ghost" id="menu-btn" aria-label="Open navigation" aria-expanded="false">☰</button>
    <div class="where"><span class="alias">${esc(it.alias)}</span>
      <span class="plain">${esc(it.label)}</span></div>
    <div class="grow"></div>
    <span id="sys-chips" style="display:flex;gap:7px;flex-wrap:wrap;justify-content:flex-end;align-items:center;"></span>
    <button id="bell" aria-haspopup="dialog" aria-expanded="false" aria-label="Notifications">
      ◔<span class="cnt" id="bell-cnt" aria-hidden="true"></span></button>`;
  document.body.insertBefore(bar, document.querySelector("main"));
  document.getElementById("bell").onclick = () => toggleDrawer();
  document.getElementById("menu-btn").onclick = () => toggleRailDrawer();
}

/* mobile rail drawer */
let railOpen = false;
function toggleRailDrawer(force) {
  const rail = document.getElementById("rail");
  const scrim = document.getElementById("scrim");
  railOpen = force !== undefined ? force : !railOpen;
  rail.classList.toggle("open", railOpen);
  scrim.classList.toggle("on", railOpen || drawerOpen);
  document.getElementById("menu-btn").setAttribute("aria-expanded", String(railOpen));
  if (railOpen) rail.querySelector("a.item").focus();
  else document.getElementById("menu-btn").focus();
}

/* ---- the notification drawer ------------------------------------------ */

let SHELL = null, drawerOpen = false, drawerTab = "needs", lastFocus = null;

const N_STYLE = {
  exception: { cls: "crit", tagOf: n => (({ interview: "Interview", assessment: "Assessment", video_interview: "Video interview", signature: "Signature" })[n.exception_type] || n.exception_type) },
  review: { cls: "warm", tagOf: () => "Review" },
  gaps: { cls: "warm", tagOf: () => "Answers" },
  fails: { cls: "soft", tagOf: () => "Failures" },
  carried: { cls: "info", tagOf: () => "Queue" },
  inbox_action: { cls: "soft", tagOf: () => "Inbox" },
  intro: { cls: "info", tagOf: () => "Welcome" },
};

function buildDrawer() {
  const scrim = document.createElement("div");
  scrim.id = "scrim";
  scrim.onclick = () => { if (drawerOpen) toggleDrawer(false); if (railOpen) toggleRailDrawer(false); };
  const d = document.createElement("div");
  d.id = "drawer";
  d.setAttribute("role", "dialog");
  d.setAttribute("aria-modal", "true");
  d.setAttribute("aria-label", "Notifications");
  d.innerHTML = `
    <div class="dhead"><h2>Alert Center</h2>
      <button class="small ghost" id="drawer-close" aria-label="Close notifications">✕</button></div>
    <div class="dtabs" role="tablist" aria-label="Notification groups">
      <button role="tab" data-tab="needs" aria-selected="true">Needs you<b id="tabn-needs"></b></button>
      <button role="tab" data-tab="system" aria-selected="false">System<b id="tabn-system"></b></button>
      <button role="tab" data-tab="completed" aria-selected="false">Completed</button>
      <button role="tab" data-tab="history" aria-selected="false">History</button>
    </div>
    <div class="dbody" id="drawer-body" aria-live="polite"></div>
    <div class="dfoot"><button class="small" id="mark-all">Mark everything read</button></div>`;
  document.body.append(scrim, d);
  document.getElementById("drawer-close").onclick = () => toggleDrawer(false);
  d.querySelectorAll("[role=tab]").forEach(t => t.onclick = () => {
    drawerTab = t.dataset.tab;
    d.querySelectorAll("[role=tab]").forEach(x => x.setAttribute("aria-selected", String(x === t)));
    renderDrawer();
  });
  document.getElementById("mark-all").onclick = async () => {
    const keys = (SHELL.notifications || []).map(n => n.key);
    if (SHELL.intro) keys.push(SHELL.intro.key);
    if (keys.length) { await post("/api/notifs/seen", { keys }); await refreshShell(); }
  };
  document.addEventListener("keydown", e => {
    if (e.key === "Escape") {
      if (drawerOpen) { e.preventDefault(); toggleDrawer(false); }
      else if (railOpen) { e.preventDefault(); toggleRailDrawer(false); }
      return;
    }
    if (e.key === "Tab" && drawerOpen) {              // keep focus inside the dialog
      const f = [...d.querySelectorAll("button, a[href]")].filter(x => x.offsetParent !== null);
      if (!f.length) return;
      const first = f[0], last = f[f.length - 1];
      if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last.focus(); }
      else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus(); }
    }
  });
}

function toggleDrawer(force) {
  const d = document.getElementById("drawer");
  const scrim = document.getElementById("scrim");
  drawerOpen = force !== undefined ? force : !drawerOpen;
  d.classList.toggle("open", drawerOpen);
  scrim.classList.toggle("on", drawerOpen || railOpen);
  document.getElementById("bell").setAttribute("aria-expanded", String(drawerOpen));
  if (drawerOpen) {
    lastFocus = document.activeElement;
    renderDrawer();
    document.getElementById("drawer-close").focus();
  } else if (lastFocus) {
    lastFocus.focus();
  }
}

function nItem(n, seen) {
  const s = N_STYLE[n.kind] || { cls: "info", tagOf: () => n.kind };
  const isSeen = seen.includes(n.key);
  const when = n.ts ? fmt.ts(n.ts) : "";
  return `<div class="nitem ${s.cls} ${isSeen ? "seen" : ""}" data-key="${esc(n.key)}">
    <div class="tx">
      <div class="tt"><span class="tag">${esc(s.tagOf(n))}</span>${esc(n.title)}</div>
      ${n.detail ? `<div class="dt">${esc(n.detail)}</div>` : ""}
      <div class="meta">${when ? esc(when) + " · " : ""}${isSeen ? "read" : "unread"}</div>
      <div class="acts">
        ${n.target ? `<a class="btn small primary" href="${esc(n.target)}" data-open="${esc(n.key)}">Open →</a>` : ""}
        ${n.kind === "exception" ? `<button class="small" data-ack="${n.app_id}" title="Acknowledge — clears this exception and logs it">Ack</button>` : ""}
        ${!isSeen ? `<button class="small ghost" data-seen="${esc(n.key)}">Mark read</button>` : ""}
      </div>
    </div>
  </div>`;
}

function renderDrawer() {
  if (!SHELL) return;
  const body = document.getElementById("drawer-body");
  const seen = SHELL.seen || [];
  const needs = (SHELL.notifications || []).filter(n => n.group === "needs_you");
  const sys = (SHELL.notifications || []).filter(n => n.group === "system");
  if (SHELL.intro) sys.unshift(SHELL.intro);
  document.getElementById("tabn-needs").textContent = needs.length || "";
  document.getElementById("tabn-system").textContent = sys.length || "";

  if (drawerTab === "completed") {
    body.innerHTML = (SHELL.completed || []).map(c => `
      <div class="nitem seen"><div class="tx">
        <div class="tt"><span class="tag">${esc(c.stage)}</span>Run finished cleanly</div>
        ${c.reason ? `<div class="dt">${esc(c.reason)}</div>` : ""}
        <div class="meta">${esc(fmt.ts(c.ts))} · ok</div>
      </div></div>`).join("")
      || `<div class="drawer-empty">No completed runs recorded yet.</div>`;
    return;
  }
  if (drawerTab === "history") {
    body.innerHTML = (SHELL.history || []).map(h => `
      <div class="nitem seen"><div class="tx">
        <div class="tt"><span class="tag">${esc(h.kind.replace(/_/g, " "))}</span>${esc(h.title)}</div>
        ${h.detail ? `<div class="dt">${esc(h.detail)}</div>` : ""}
        <div class="meta">${esc(fmt.ts(h.ts))}</div>
      </div></div>`).join("")
      || `<div class="drawer-empty">No resolved items yet.</div>`;
    return;
  }
  const list = drawerTab === "needs" ? needs : sys;
  body.innerHTML = list.map(n => nItem(n, seen)).join("")
    || `<div class="drawer-empty"><span class="big">✓</span>${drawerTab === "needs"
      ? "Nothing needs you. The system is on its own." : "No system notices."}</div>`;

  body.querySelectorAll("[data-seen]").forEach(b => b.onclick = async () => {
    b.disabled = true;
    try { await post("/api/notifs/seen", { keys: [b.dataset.seen] }); await refreshShell(); }
    catch (e) { b.disabled = false; }
  });
  body.querySelectorAll("[data-open]").forEach(a => a.onclick = () => {
    // opening implies read; fire-and-forget before navigation
    try { navigator.sendBeacon ? navigator.sendBeacon("/api/notifs/seen", new Blob([JSON.stringify({ keys: [a.dataset.open] })], { type: "application/json" })) : post("/api/notifs/seen", { keys: [a.dataset.open] }); } catch (e) {}
  });
  body.querySelectorAll("[data-ack]").forEach(b => b.onclick = async () => {
    b.disabled = true;
    try { await post(`/api/exceptions/${b.dataset.ack}/ack`); await refreshShell(); }
    catch (err) { b.disabled = false; alert(err.message); }
  });
}

/* ---- topbar chips + bell badge ---------------------------------------- */

function renderChips(d) {
  const box = document.getElementById("sys-chips");
  if (!box) return;
  const chips = [];
  if (d.paused) chips.push(`<span class="syschip warn"><span class="d"></span>PAUSED</span>`);
  else if (d.dry_run) chips.push(`<span class="syschip warn"><span class="d"></span>DRY RUN</span>`);
  else chips.push(`<span class="syschip live"><span class="d"></span>LIVE</span>`);
  for (const r of d.running || [])
    chips.push(`<span class="syschip run"><span class="d"></span>${esc(r.stage)} running</span>`);
  if (d.auto && d.auto.enabled && d.auto.awaiting_review)
    chips.push(`<span class="syschip warn optional" title="The auto-submit head stopped itself until you review its screenshots (Submissions page)."><span class="d"></span>head ${d.auto.live_count}/${d.auto.verify_first_n}</span>`);
  if (d.spend)
    chips.push(`<span class="syschip optional" title="API spend month-to-date vs the monthly cap"><span class="d"></span>$${(+d.spend.mtd).toFixed(2)}/$${d.spend.cap}</span>`);
  if ((d.next_runs || []).length && !(d.running || []).length) {
    const n = d.next_runs[0];
    chips.push(`<span class="syschip optional" title="Next scheduled job"><span class="d"></span>${esc(ampm(n.at.slice(11, 16)))} ${esc(n.label.toLowerCase())}</span>`);
  }
  box.innerHTML = chips.join("");
}

function renderBell(d) {
  const cnt = document.getElementById("bell-cnt");
  const bell = document.getElementById("bell");
  if (!cnt) return;
  const seen = d.seen || [];
  const needs = (d.notifications || []).filter(n => n.group === "needs_you");
  const unseenNeeds = needs.filter(n => !seen.includes(n.key)).length;
  const sysUnseen = (d.notifications || []).filter(n => n.group === "system" && !seen.includes(n.key)).length
    + (d.intro ? 1 : 0);
  if (unseenNeeds) { cnt.textContent = unseenNeeds; cnt.classList.remove("quiet"); }
  else if (sysUnseen) { cnt.textContent = sysUnseen; cnt.classList.add("quiet"); }
  else cnt.textContent = "";
  bell.setAttribute("aria-label",
    `Notifications: ${needs.length} need you, ${sysUnseen} unread notices`);
}

async function refreshShell() {
  try {
    const d = await fetchJSON("/api/shell");
    SHELL = d;
    renderChips(d);
    renderBell(d);
    if (drawerOpen) renderDrawer();
    const qb = document.getElementById("badge-queue");
    if (qb) qb.textContent = d.queue_count > 0 ? d.queue_count : "";
    const gb = document.getElementById("badge-gaps");
    if (gb) gb.textContent = d.gaps_open > 0 ? d.gaps_open : "";
    const nx = document.getElementById("nav-next");
    if (nx && (d.next_runs || []).length) {
      const n = d.next_runs[0];
      nx.textContent = `next: ${n.label.toLowerCase()} ${ampm(n.at.slice(11, 16))}`;
    }
    document.dispatchEvent(new CustomEvent("shell", { detail: d }));
  } catch (e) { /* shell poll failure is non-fatal; next poll retries */ }
}

/* one orchestrated load moment (CSS handles reduced-motion) */
function orchestrate() {
  const kids = [...document.querySelector("main").children].slice(0, 8);
  kids.forEach((el, i) => {
    el.classList.add("rise");
    el.style.setProperty("--rise-d", `${i * 45}ms`);
  });
  requestAnimationFrame(() => requestAnimationFrame(() => document.body.classList.add("loaded")));
}

function initShell() {
  const active = document.body.dataset.page;
  try { if (localStorage.getItem(RAIL_PREF)) document.body.classList.add("rail-min"); } catch (e) {}
  const skip = document.createElement("a");
  skip.className = "skip";
  skip.href = "#main";
  skip.textContent = "Skip to content";
  document.body.prepend(skip);
  buildRail(active);
  buildTopbar(active);
  buildDrawer();
  document.querySelectorAll("#rail a.item").forEach(a =>
    a.addEventListener("click", () => { if (railOpen) toggleRailDrawer(false); }));
  orchestrate();
  refreshShell();
  setInterval(refreshShell, 45000);
}

document.addEventListener("DOMContentLoaded", initShell);
