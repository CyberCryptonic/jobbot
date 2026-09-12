/* JobBot scenes3d — the eight page scenes built on ops3d (session 14).
   Deterministic, hand-placed layouts (no force graphs). Every value shown is
   real application data; packets fire only for real events; idle is calm.
   Each builder returns { scene, applyEvent(e), setData(...) }. */

import * as THREE from "three";
import { OpsScene, EventFeed, PAL, build, env, supportsWebGL, reducedMotion,
         lowPowerPref, setLowPowerPref } from "/assets/ops3d.js";

export { EventFeed, supportsWebGL, reducedMotion };

/* v2: the engine's semantic library provides pylon/platform and the rest */
const SILVER = PAL.silver;

/* shared toolbar: mode segments + badge + pause + reset + low power */
export function sceneTools(container, { modes, onMode, scene, feed, extra = "" }) {
  const seg = modes.map(([id, label]) =>
    `<button type="button" data-mode="${id}" aria-pressed="false">${label}</button>`).join("");
  container.innerHTML = `
    <span class="seg" role="group" aria-label="View mode">${seg}</span>
    ${feed ? `<span class="mode-badge" data-badge><span class="d"></span><span data-badge-t>PAUSED</span></span>
    <button type="button" class="small ghost" data-pause aria-pressed="false" title="Pause or resume scene activity">⏸</button>` : ""}
    ${extra}
    <button type="button" class="small ghost" data-resetcam title="Reset the camera (R)">⌖ Reset</button>
    <button type="button" class="small ghost" data-lowpower aria-pressed="${lowPowerPref()}" title="Low-power mode (lower resolution, fewer effects)">◐</button>`;
  const badge = container.querySelector("[data-badge]");
  const badgeT = container.querySelector("[data-badge-t]");
  const setBadge = m => {
    if (!badge) return;
    badge.className = "mode-badge " + (m === "live" ? "live" : m.startsWith("replay") ? "replay" : "");
    badgeT.textContent = m === "live" ? "LIVE" : m.startsWith("replay") ? "REPLAY · HISTORICAL" : "PAUSED";
  };
  const setMode = id => {
    container.querySelectorAll("[data-mode]").forEach(b =>
      b.setAttribute("aria-pressed", String(b.dataset.mode === id)));
    onMode(id);
  };
  container.querySelectorAll("[data-mode]").forEach(b => b.onclick = () => setMode(b.dataset.mode));
  const pauseBtn = container.querySelector("[data-pause]");
  if (pauseBtn) pauseBtn.onclick = () => {
    const on = pauseBtn.getAttribute("aria-pressed") !== "true";
    pauseBtn.setAttribute("aria-pressed", String(on));
    if (scene()) scene().paused = on;
    if (feed) { if (on) feed.pause(); else feed.resumeLive(); }
    setBadge(on ? "paused" : (feed ? feed.mode : "paused"));
  };
  container.querySelector("[data-resetcam]").onclick = () => scene() && scene().resetCamera();
  const lp = container.querySelector("[data-lowpower]");
  lp.onclick = () => {
    const on = lp.getAttribute("aria-pressed") !== "true";
    lp.setAttribute("aria-pressed", String(on));
    setLowPowerPref(on);
    location.reload();                        // renderer settings apply at init
  };
  return { setBadge, setMode };
}

/* one-call page mount: WebGL check, tools, badge, live feed, fallback note */
export function initPageScene({ tools, host, note, builder, buildOpts = {},
                                wantFeed = true, extra = "", minWidth = 900 }) {
  // the host ships with a real "Initializing spatial view" placeholder; clear
  // it once the scene exists, or fold the host away when 3D is not happening
  const clearLoading = ok => {
    const l = host.querySelector(".scene-loading");
    if (l) l.remove();
    host.classList.remove("loading");
    if (!ok) host.classList.add("hide");
  };
  if (window.innerWidth <= minWidth || !supportsWebGL()) {
    clearLoading(false);
    tools.classList.add("hide");
    return null;
  }
  const built = builder(host, buildOpts);
  if (!built) {
    clearLoading(false);
    if (note) { note.textContent = "3D scene unavailable on this device — the records below carry everything."; note.classList.remove("hide"); }
    tools.classList.add("hide");
    return null;
  }
  clearLoading(true);
  host.classList.remove("hide");
  let T = null;
  const feed = wantFeed ? new EventFeed({
    onEvent: (e, ctx) => built.applyEvent && built.applyEvent(e, ctx),
    onMode: m => T && T.setBadge(m === "replay-done" ? "replay" : m),
  }) : null;
  T = sceneTools(tools, {
    modes: [["scene", "3D scene"], ["off", "Hide"]],
    onMode: id => {
      host.classList.toggle("hide", id !== "scene");
      if (id === "scene") { built.scene._resize(); built.scene.requestRender(); if (feed && feed.mode === "paused") feed.resumeLive(); }
      else if (feed) feed.pause();
    },
    scene: () => built.scene, feed, extra,
  });
  T.setMode("scene");
  if (feed) feed.live();
  built.tools = T;
  built.feed = feed;
  return built;
}

/* First-use orientation tour for the Agent Mesh. Runs once (server-persisted
   key tour-v1), fully keyboard-driven, skippable at every step. Camera flights
   are the real presets; under reduced motion the caller never starts it. */
export function startAgentsTour(built, { onDone } = {}) {
  const scene = built.scene;
  const steps = [
    { t: "This is the JobBot floor", p: "Every machine here is one real agent. Drag to orbit, scroll to zoom, click any machine to open its record below.", go: () => scene.resetCamera() },
    { t: "The reactor is JobBot itself", p: "The core at center orchestrates everything. Its ember heart beats while the pipeline is autonomous; the arc at its base is real budget spent this month; the segmented ring is queue pressure.", go: () => scene.focusOn("core", { radius: 8.5 }) },
    { t: "Work flows left to right", p: "Discovery scans the boards, Scoring swings its gauge, the Letter writer drafts on its table, and the Submission checkpoint opens its doors only for an approved application.", go: () => scene.setPreset("workflow") },
    { t: "Replies come back as telemetry", p: "The receiver dish catches employer email and sorts it down real chutes. Inbound traffic is silver; nothing on this floor is invented.", go: () => scene.focusOn("inbox", { radius: 8 }) },
    { t: "Amber means waiting on you", p: "The quarantine pods hold jobs only you may submit, and your console is the only release authority. Camera presets up top jump straight to any of this.", go: () => scene.setPreset("review") },
  ];
  let i = 0;
  const veil = document.createElement("div"); veil.className = "tour-veil";
  const card = document.createElement("div"); card.className = "tour-card";
  card.setAttribute("role", "dialog"); card.setAttribute("aria-label", "Agent Mesh orientation");
  card.style.right = "26px"; card.style.bottom = "26px";
  const finish = skipped => {
    veil.remove(); card.remove();
    document.removeEventListener("keydown", onKey, true);
    scene.resetCamera();
    fetch("/api/notifs/seen", { method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ keys: ["tour-v1"] }) }).catch(() => {});
    if (onDone) onDone(skipped);
  };
  const render = () => {
    const s = steps[i];
    card.innerHTML = `
      <h3>${s.t}</h3><p>${s.p}</p>
      <div class="tour-foot">
        <span class="tour-dots">${steps.map((_, k) => `<i class="${k === i ? "on" : ""}"></i>`).join("")}</span>
        <button type="button" class="small ghost" data-skip>Skip tour</button>
        ${i > 0 ? `<button type="button" class="small ghost" data-back>Back</button>` : ""}
        <button type="button" class="small" data-next>${i === steps.length - 1 ? "Done" : "Next"}</button>
      </div>`;
    card.querySelector("[data-skip]").onclick = () => finish(true);
    const back = card.querySelector("[data-back]");
    if (back) back.onclick = () => { i--; steps[i].go(); render(); };
    card.querySelector("[data-next]").onclick = () => {
      if (i === steps.length - 1) return finish(false);
      i++; steps[i].go(); render();
    };
    card.querySelector("[data-next]").focus();
  };
  const onKey = e => {
    if (e.key === "Escape") { e.preventDefault(); finish(true); }
    else if (e.key === "ArrowRight" || e.key === "Enter") { e.preventDefault(); card.querySelector("[data-next]").click(); }
    else if (e.key === "ArrowLeft" && i > 0) { e.preventDefault(); i--; steps[i].go(); render(); }
  };
  document.addEventListener("keydown", onKey, true);
  veil.onclick = () => finish(true);
  document.body.append(veil, card);
  steps[0].go(); render();
  return { stop: () => finish(true) };
}

const STAGE_NODE = { discovery: "discovery", scoring: "scoring", materials: "materials",
  submission: "submission", inbox: "inbox", followup: "followup", report: "report", chat: "chat" };

/* ══════════ AGENTS — Circular AI Operations Chamber (v3) ══════════
   One round chamber: the reactor core elevated at dead center, agent
   workstations radial around it, work flowing clockwise along the back
   arc (intake → discovery → scoring → drafting → egress), telemetry and
   human review around the front. Sources and employers stand OUTSIDE the
   chamber wall at the intake/egress gaps. Environment: segmented floor
   with an embedded conduit ring, wall arcs with lit slits, background
   machinery silhouettes, an observation rail, directional chevrons at the
   gates, and pooled light under the core and the operator. */

const D = Math.PI / 180;
const ringPos = (deg, r, y = 0.05) => [Math.cos(deg * D) * r, y, -Math.sin(deg * D) * r];

export function buildAgents(host, { onSelect }) {
  const scene = new OpsScene(host, {
    ariaLabel: "Circular operations chamber: the JobBot Core reactor at center, its agents as radial workstations, external feeds and employers outside the wall, live work flowing between them.",
    camera: { radius: 16.4, phi: 0.965, theta: 0.03, target: [0, 0.55, -0.55], maxTheta: 1.25, panLimit: 3, maxR: 22 },
    shadowBounds: 12,
    onSelect,
    presets: {
      workflow: { radius: 12.4, theta: -0.62, phi: 1.02, target: [-1.2, 0.4, -2.6] },
      review: { radius: 11.6, theta: 0.72, phi: 0.96, target: [-3.4, 0.35, 2.6] },
    },
  });
  if (!scene.ok) return null;

  /* ---- environment ---- */
  scene.scene.add(env.floorDisc(9.6, { seams: 16, channelR: 6.3 }));
  const wallBack = env.wallArc(9.0, 28 * D, 152 * D, { slits: 6 });
  const wallFrontL = env.wallArc(9.0, 196 * D, 262 * D, { slits: 3 });
  const wallFrontR = env.wallArc(9.0, 278 * D, 336 * D, { slits: 3 });
  scene.scene.add(wallBack, wallFrontL, wallFrontR);
  for (const [a, seed] of [[52, 3], [88, 7], [122, 11], [206, 5], [305, 9]]) {
    const s = env.silhouette(seed);
    s.position.set(...ringPos(a, 10.6, 0));
    s.rotation.y = a * D + Math.PI / 2;
    scene.scene.add(s);
  }
  scene.scene.add(env.rail(7.7, -78 * D, -28 * D));
  const chevIn = env.chevrons(3);
  chevIn.position.set(...ringPos(162, 7.6, 0));
  chevIn.rotation.y = (162 + 180) * D;
  const chevOut = env.chevrons(3);
  chevOut.position.set(...ringPos(14, 7.4, 0));
  chevOut.rotation.y = 14 * D;
  scene.scene.add(chevIn, chevOut);
  scene.scene.add(env.poolLight(2.6));
  const opPool = env.poolLight(1.7);
  opPool.position.set(...ringPos(-144, 6.9, 0.012));
  scene.scene.add(opPool);
  // radial data conduits from the core apron to each workstation
  for (const a of [146, 113, 80, 47, -24, -60, -96, -131, -167]) {
    const [x1, , z1] = ringPos(a, 1.9, 0);
    const [x2, , z2] = ringPos(a, 4.7, 0);
    scene.scene.add(env.conduit(x1, z1, x2, z2));
  }
  // gate posts flanking the intake and egress wall gaps
  for (const [a, w] of [[160, 1], [176, 1], [4, 1], [26, 1]]) {
    const post = build.wall(0.9, { h: 0.7 });
    post.position.set(...ringPos(a, 8.9, 0));
    post.rotation.y = a * D + Math.PI / 2;
    scene.scene.add(post);
  }

  /* ---- zone sectors (floor captions on the ring) ---- */
  const sector = (label, a1, a2) => scene.addZone({
    label, shape: "arc", r1: 4.1, r2: 6.55,
    a1: a1 * D, a2: a2 * D, labelAt: ringPos((a1 + a2) / 2, 6.9, 0.05) });
  sector("Recon / intake", 134, 160);
  sector("Analysis", 100, 127);
  sector("Production", 67, 94);
  sector("Controlled execution", 34, 61);
  sector("Inbound telemetry", -38, -11);
  sector("Timed response", -73, -47);
  sector("Audit", -110, -83);
  sector("Operator interface", -144, -118);
  sector("Quarantine", -180, -152);

  /* ---- stations ---- */
  const N = (id, label, sub, deg, r, kind, scale, opts = {}) => {
    const n = scene.addNode({ id, label, sub, pos: ringPos(deg, r), kind, scale,
      focusRadius: opts.fr || 8, chrome: opts.chrome || "auto" });
    n.group.rotation.y = deg * D - Math.PI / 2 + (opts.spin || 0);  // face the core
    return n;
  };
  N("boards", "Job boards & feeds", "external sources", 168, 8.6, "pylon", 1.15, { spin: Math.PI });
  N("discovery", "Discovery", "reconnaissance lens", 146, 5.3, "radar", 1.5);
  N("scoring", "Scoring", "evaluation gauge", 113, 5.3, "rings", 1.45);
  N("materials", "Letter writer", "document drafting table", 80, 5.3, "forge", 1.6);
  N("submission", "Submission head", "egress checkpoint", 47, 5.3, "gateway", 1.5);
  N("employers", "Employers / ATS", "secured destination", 12, 8.6, "terminals", 1.25, { spin: Math.PI });
  N("inbox", "Inbox reader", "receiver + sorting tray", -24, 5.3, "antenna", 1.5);
  N("followup", "Follow-ups", "timed response loop", -62, 4.95, "loop", 1.35);
  N("report", "Nightly report", "audit ledger + seal", -97, 4.6, "vault", 1.35);
  N("chat", "Chat agent", "waveform console", -128, 5.0, "node", 1.45);
  N("you", "You", "operator command station", -145, 7.1, "console", 1.35);
  N("queue", "Manual queue", "quarantine pods", -171, 5.9, "chamber", 1.4);
  scene.addNode({ id: "core", label: "JobBot Core", sub: "orchestration reactor",
    pos: [0, 0.12, 0], kind: "core", scale: 1.9, focusRadius: 9 });

  // label anchors: back arc above, front arc below the machine (¾-top view)
  for (const id of ["inbox", "followup", "report", "chat", "you", "queue", "core"]) {
    const n = scene.nodes.get(id);
    n.labelOffset = -0.34;
    n.el.dataset.below = "1";
  }
  scene.nodes.get("core").labelOffset = -0.62;
  scene.nodes.get("discovery").labelOffset = 2.0;
  scene.nodes.get("materials").labelOffset = 1.85;
  scene.nodes.get("scoring").labelOffset = 1.7;
  scene.nodes.get("submission").labelOffset = 1.6;

  /* ---- work paths ---- */
  const at = id => { const v = new THREE.Vector3(); scene.nodes.get(id).group.getWorldPosition(v); v.y += 0.4; return [v.x, v.y, v.z]; };
  const P = (id, a, b, arc, opts) => scene.addPath(id, [at(a), at(b)], { arc, ...opts });
  P("p_src", "boards", "discovery", 0.55);
  P("p_score", "discovery", "scoring", 0.5);
  P("p_mat", "scoring", "materials", 0.5);
  P("p_sub", "materials", "submission", 0.5);
  P("p_out", "submission", "employers", 0.6);
  P("p_in", "employers", "inbox", 0.7);
  P("p_fu", "inbox", "followup", 0.45);
  P("p_fu_out", "followup", "employers", 1.05);
  P("p_core_in", "scoring", "core", 0.5);
  P("p_core_tel", "inbox", "core", 0.5);
  P("p_report", "core", "report", 0.5);
  P("p_chat", "chat", "you", 0.4);
  P("p_q", "submission", "queue", 1.5);
  P("p_release", "queue", "you", 0.42);
  P("p_letters", "core", "materials", 0.5);

  const flash = (id, state, line) => scene.setNodeState(id, { state, line });
  const errPath = { discovery: "p_src", scoring: "p_score", materials: "p_mat",
    submission: "p_out", inbox: "p_in", followup: "p_fu_out", report: "p_report", chat: "p_chat" };
  const tempRun = (id, line, ms = 1600) => {
    const prev = scene.nodes.get(id).state;
    flash(id, "run", line);
    setTimeout(() => { if (scene.nodes.get(id).state === "run") flash(id, prev === "run" ? "ok" : prev, ""); }, ms);
  };

  function applyEvent(e) {
    const stage = STAGE_NODE[e.stage];
    if (e.type === "run_start" && stage) flash(stage, "run", "working right now");
    if (e.type === "run_end" && stage)
      flash(stage, e.outcome === "fail" ? "fail" : "ok",
        e.outcome === "fail" ? ("failed · " + (e.reason || "")) : "ran just now · ok");
    if (e.type === "agent_error" && stage) {
      flash(stage, "fail", "error · " + (e.reason || "see log"));
      if (errPath[stage]) scene.setPathState(errPath[stage], "error");
      return;
    }
    const fire = (path, opts = {}) => {
      scene.setPathState(path, opts.color === PAL.silver ? "in" : opts.color === PAL.warn ? "warn" : "live");
      scene.firePacket(path, opts);
      setTimeout(() => scene.setPathState(path, "today"), 1700);
    };
    switch (e.type) {
      case "job_discovered": tempRun("discovery", "scanning sources…"); fire("p_src", { count: e.count || 1 }); break;
      case "job_scored": scene.act("scoring", "gauge"); fire("p_score", {}); break;
      case "job_queued": fire("p_core_in", {}); break;
      case "letter_started": flash("materials", "run", "drafting a letter…"); scene.act("materials", "write", { dur: 2400 }); fire("p_letters", {}); break;
      case "letter_completed": scene.act("materials", "write", { dur: 1200 }); fire("p_sub", {}); flash("materials", "ok", "letter finished"); break;
      case "submission_prepared": fire("p_sub", {}); break;
      case "submission_sent": tempRun("submission", "gate open — transmitting…", 2000); fire("p_out", {}); break;
      case "submission_handoff": fire("p_q", { color: PAL.warn }); break;
      case "submission_waiting_review": flash("submission", "blocked", "HOLDING — awaiting your review"); break;
      case "submission_skipped": flash("submission", "ok", "skipped · " + (e.reason || "missing answer")); break;
      case "email_received": case "email_classified":
        scene.act("inbox", "receive"); fire("p_in", { color: PAL.silver }); break;
      case "interview_detected": case "action_required":
        fire("p_release", { color: PAL.warn, reverse: true }); flash("you", "blocked", "needs your hand"); break;
      case "followup_scheduled": fire("p_fu", {}); break;
      case "followup_sent": scene.act("followup", "loop", { dur: 1600 }); fire("p_fu_out", {}); break;
      case "report_generated": scene.act("report", "stamp"); fire("p_report", {}); flash("report", "ok", "report sealed"); break;
    }
  }

  function setData(A) {
    const today = new Date().toISOString().slice(0, 10);
    for (const a of A.agents) {
      const id = STAGE_NODE[a.stage];
      if (!id) continue;
      let state = "idle", line = a.last ? `ran ${a.last.ts.slice(11, 16)} · ${a.last.outcome}` : "idle";
      if (a.running) { state = "run"; line = "working right now"; }
      else if (a.stage === "submission" && A.head.enabled && A.head.awaiting_review) { state = "blocked"; line = "HOLDING — awaiting your review"; }
      else if (a.last && a.last.outcome === "fail") { state = "fail"; line = "failed · " + (a.last.reason || ""); }
      else if (a.always_on) { state = "ok"; line = "always on — listening"; }
      else if (a.last && a.last.ts.slice(0, 10) === today && a.last.outcome === "ok") state = "ok";
      scene.setNodeState(id, { state, line,
        metric: `${a.today.metric} ${a.today.metric_label}` +
          (a.backlog ? ` · ▲${a.backlog}` : "") +
          (a.spend.today > 0 ? ` · $${a.spend.today.toFixed(2)}` : "") });
    }
    scene.setNodeState("queue", { state: A.queue_count ? "blocked" : "idle",
      line: A.queue_count ? "holding for your review" : "empty",
      metric: `${A.queue_count} card${A.queue_count === 1 ? "" : "s"}` });
    scene.setNodeState("you", { state: "idle", line: "release authority", metric: "" });
    const c = A.core;
    scene.setNodeState("core", {
      state: c.state === "AUTONOMOUS" ? "ok" : c.state === "PAUSED" ? "fail" : "blocked",
      line: c.state,
      metric: `${c.applied_today_auto}/${c.daily_target} auto · $${c.spend_mtd.toFixed(2)}/$${c.cap} · queue ${c.queue_count}/${c.queue_cap}` });

    // the gateway's hold lamp burns amber only while a review hold is real
    const gw = scene.nodes.get("submission").group.userData;
    if (gw.lamp) gw.lamp.material.emissiveIntensity =
      (A.head.enabled && A.head.awaiting_review) ? 0.95 : 0.18;

    // the reactor's gauges are real: heart, safety lamp, budget arc, spine
    const cu = scene.nodes.get("core").group.userData;
    const heartI = { AUTONOMOUS: 0.4, "REVIEW HOLD": 0.16, "DRY RUN": 0.16, PAUSED: 0.05 }[c.state] ?? 0.3;
    cu.heart.material.emissiveIntensity = heartI;
    cu.safety.material.emissive.setHex(c.state === "PAUSED" ? PAL.fail : c.state === "AUTONOMOUS" ? 0x2f3236 : PAL.warn);
    cu.safety.material.emissiveIntensity = c.state === "AUTONOMOUS" ? 0.1 : 0.8;
    const bFrac = Math.max(0.02, Math.min(1, c.spend_mtd / Math.max(1, c.cap)));
    cu.budget.geometry.dispose();
    cu.budget.geometry = new THREE.TorusGeometry(0.5, 0.018, 8, 48, Math.PI * 2 * bFrac).clone();
    const qFrac = Math.min(1, c.queue_count / Math.max(1, c.queue_cap));
    cu.spine.forEach((m, i) => { m.emissiveIntensity = (i / cu.spine.length) < qFrac ? 1.0 : 0.03; });

    // attention preset frames whatever needs eyes right now
    const hot = [...scene.nodes.values()].filter(n => n.state === "fail" || n.state === "blocked");
    if (hot.length) {
      const cx = hot.reduce((s, n) => s + n.group.position.x, 0) / hot.length;
      const cz = hot.reduce((s, n) => s + n.group.position.z, 0) / hot.length;
      scene.presets.attention = { radius: 11.5, theta: cx > 0 ? -0.35 : 0.35, phi: 0.98, target: [cx * 0.55, 0.3, cz * 0.55] };
    } else scene.presets.attention = null;

    for (const a of A.agents) {
      const p = errPath[STAGE_NODE[a.stage] || ""];
      if (p && a.last && a.last.ts.slice(0, 10) === today)
        scene.setPathState(p, a.last.outcome === "fail" ? "error" : "today");
    }
    scene.requestRender();
  }
  return { scene, applyEvent, setData };
}

/* ══════════════ OVERVIEW — Mission Control round table (v2) ══════════════ */

export function buildOverview(host, { onZone }) {
  const scene = new OpsScene(host, {
    ariaLabel: "Mission table: a circular miniature of the whole JobBot operation with today's real volumes. Tap any station to open its page.",
    camera: { radius: 11.0, phi: 0.7, theta: 0.0, target: [0, 0, 0.1], maxTheta: 1.0, panLimit: 1.6 },
    onSelect: onZone,
  });
  if (!scene.ok) return null;

  // one round command dais; stations arc around the reactor like a war table
  const dais = new THREE.Group();
  const disc = new THREE.Mesh(new THREE.CylinderGeometry(5.2, 5.4, 0.1, 56),
    new THREE.MeshStandardMaterial({ color: 0x1b1e22, roughness: 0.85, metalness: 0.15 }));
  disc.position.y = -0.05;
  const rim = new THREE.Mesh(new THREE.TorusGeometry(5.3, 0.03, 8, 72),
    new THREE.MeshStandardMaterial({ color: PAL.metalDark, roughness: 0.35, metalness: 0.85 }));
  rim.rotation.x = Math.PI / 2; rim.position.y = 0.02;
  dais.add(disc, rim);
  scene.scene.add(dais);

  // command deck: ground the dais, curve a wall behind it, keep oversight airy
  scene.scene.add(env.floorDisc(7.6, { seams: 10, apron: 2.4 }));
  scene.scene.add(env.wallArc(7.9, 0.5, Math.PI - 0.5, { h: 2.1, slits: 5 }));
  for (const [a, seed] of [[70, 4], [110, 8], [250, 6]]) {
    const s = env.silhouette(seed);
    s.position.set(Math.cos(a * Math.PI / 180) * 9.2, 0, -Math.sin(a * Math.PI / 180) * 9.2);
    s.rotation.y = a * Math.PI / 180 + Math.PI / 2;
    scene.scene.add(s);
  }
  scene.scene.add(env.rail(6.6, -1.05, -0.35));
  scene.scene.add(env.poolLight(2.2));

  const R = 3.9;
  const at = deg => { const a = deg * Math.PI / 180; return [Math.cos(a) * R, 0.02, -Math.sin(a) * R]; };
  const stations = [
    ["src", "Sources", "boards · pages · alerts", 168, "pylon", 0.95],
    ["/agent", "Discover + score", "", 128, "radar", 0.9],
    ["/applications", "Pipeline", "", 90, "rings", 0.9],
    ["/submissions", "Egress", "", 52, "gateway", 0.9],
    ["emp", "Employers", "", 12, "terminals", 0.85, -0.7],
    ["/inbox", "Telemetry", "", -40, "antenna", 0.9],
    ["/queue", "Your review bay", "", -140, "chamber", 0.9],
  ];
  for (const [id, label, sub, deg, kind, sc, rot] of stations) {
    const n = scene.addNode({ id, label, sub, pos: at(deg), kind, scale: sc, focusRadius: 5.5 });
    if (rot) n.group.rotation.y = rot;
  }
  scene.addNode({ id: "/", label: "JobBot Core", sub: "tap any station to open its page",
    pos: [0, 0.02, 0], kind: "core", scale: 0.9, focusRadius: 5.5 });
  for (const id of ["/inbox", "/queue"]) {               // front arc labels go below
    const n = scene.nodes.get(id);
    n.labelOffset = -0.3;
    n.el.dataset.below = "1";
  }
  scene.nodes.get("/").labelOffset = -0.5;
  scene.nodes.get("/").el.dataset.below = "1";

  // work flows around the rim; telemetry and review return through the center
  const seg = (id, d1, d2, arc = 0.45) => scene.addPath(id, [
    (() => { const p = at(d1); p[1] = 0.35; return p; })(),
    (() => { const p = at(d2); p[1] = 0.35; return p; })()], { arc });
  seg("in", 168, 128);
  seg("mid", 128, 90);
  seg("out", 90, 52);
  seg("send", 52, 12, 0.55);
  seg("tel", 12, -40, 0.7);
  scene.addPath("core_tel", [(() => { const p = at(-40); p[1] = 0.35; return p; })(), [0, 0.6, 0]], { arc: 0.5 });
  scene.addPath("review", [[0, 0.6, 0], (() => { const p = at(-140); p[1] = 0.35; return p; })()], { arc: 0.5 });

  // two real-data columns beside the pipeline station: found vs applied today
  const pillars = [];
  for (let i = 0; i < 2; i++) {
    const m = new THREE.Mesh(new THREE.BoxGeometry(0.2, 1, 0.2),
      new THREE.MeshStandardMaterial({ color: PAL.emberDeep, emissive: PAL.ember,
        emissiveIntensity: 0.25, roughness: 0.5 }));
    const p = at(80);
    m.position.set(p[0] + (i ? 0.34 : 0) - 0.4, 0.05, p[2] + 0.75);
    scene.scene.add(m);
    pillars.push(m);
  }

  function setData({ found, applied, needs, queue, state }) {
    const cap = Math.max(found, applied, 1);
    [[found, 0], [applied, 1]].forEach(([v, i]) => {
      const h = 0.12 + 0.85 * (v / cap);
      pillars[i].scale.y = h;
      pillars[i].position.y = 0.05 + h / 2;
    });
    scene.setNodeState("/agent", { line: `${found} found today`, metric: "" });
    scene.setNodeState("/applications", { line: `${applied} applied today`, metric: "" });
    scene.setNodeState("/queue", { state: queue ? "blocked" : "idle", line: `${queue} waiting on you` });
    scene.setNodeState("/", { state: state === "AUTONOMOUS" ? "ok" : "blocked", line: state,
      metric: needs ? `${needs} item${needs > 1 ? "s need" : " needs"} you` : "nothing needs you" });
    const cu = scene.nodes.get("/").group.userData;
    cu.heart.material.emissiveIntensity = state === "AUTONOMOUS" ? 0.4 : 0.15;
    cu.safety.material.emissiveIntensity = state === "AUTONOMOUS" ? 0.1 : 0.8;
    scene.requestRender();
  }
  function applyEvent(e) {
    if (e.type === "job_discovered") { scene.setPathState("in", "live"); scene.firePacket("in", { count: e.count || 1 }); }
    if (e.type === "job_scored") scene.firePacket("mid", {});
    if (e.type === "letter_completed") scene.firePacket("out", {});
    if (e.type === "submission_sent") { scene.setPathState("send", "live"); scene.firePacket("send", {}); }
    if (e.type === "email_classified") { scene.setPathState("tel", "in"); scene.firePacket("tel", { color: PAL.silver }); scene.firePacket("core_tel", { color: PAL.silver }); }
    if (e.type === "interview_detected" || e.type === "action_required") scene.firePacket("review", { color: PAL.warn });
  }
  return { scene, setData, applyEvent };
}

/* ══════════════ QUEUE — Human Intervention & Quarantine Bay (v2) ══════════ */

export function buildQueue(host, { onPick }) {
  const scene = new OpsScene(host, {
    ariaLabel: "Quarantine bay: each sealed pod is one job waiting for your manual action; the selected pod sits on the inspection platform.",
    camera: { radius: 10.0, phi: 0.82, theta: 0, target: [0, 0.1, 0.2], maxTheta: 0.9, panLimit: 1.2 },
    onSelect: onPick,
  });
  if (!scene.ok) return null;
  scene.addZone({ label: "Inspection platform", x: 0, z: 1.3, w: 2.6, d: 2.4 });
  scene.addZone({ label: "Quarantine shelf", shape: "arc", x: 0, z: 1.3,
    r1: 3.7, r2: 6.4, a1: Math.PI * 0.22, a2: Math.PI * 0.78, labelAt: [0, 0.1, -4.4] });
  const plat = build.platform();
  plat.position.set(0, 0.02, 1.3);
  scene.scene.add(plat);

  // containment chamber: floor, curved containment wall behind the shelf,
  // review pool over the platform, release chevrons toward the operator
  const room = new THREE.Group();
  room.add(env.floorRect(16, 11, { border: 2 }));
  room.position.z = 0.4;
  scene.scene.add(room);
  const wallQ = env.wallArc(7.3, Math.PI * 0.18, Math.PI * 0.82, { h: 2.0, slits: 5 });
  wallQ.position.set(0, 0, 1.3);
  scene.scene.add(wallQ);
  const qPool = env.poolLight(2.0);
  qPool.position.set(0, 0.012, 1.3);
  scene.scene.add(qPool);
  const relChev = env.chevrons(3, { lit: 0.16 });
  relChev.position.set(1.6, 0, 1.55);
  relChev.rotation.y = -0.12;
  scene.scene.add(relChev);
  for (const [x, z, seed] of [[-8.2, -2.2, 4], [8.4, -1.4, 9]]) {
    const s = env.silhouette(seed);
    s.position.set(x, 0, z);
    s.rotation.y = x > 0 ? -Math.PI / 3 : Math.PI / 3;
    scene.scene.add(s);
  }
  scene.addNode({ id: "you", label: "You", sub: "release authority", pos: [3.8, 0.05, 1.7], kind: "console", scale: 0.9 });
  scene.addPath("release", [[0, 0.5, 1.3], [3.8, 0.5, 1.7]], { arc: 0.6 });

  // pods stage on two shallow arcs behind the platform; angle → screen spread
  const arcPos = (idx, row) => {
    const per = 6;
    const k = idx % per, n = per;
    const span = row ? [131, 49] : [121, 59];
    const a = (span[0] - (k * ((span[0] - span[1]) / (n - 1)))) * Math.PI / 180;
    const r = row ? 5.9 : 4.55;
    return [Math.cos(a) * r, 0.05, 1.3 - Math.sin(a) * r];
  };

  let items = [];
  function setData(cards, selectedId) {
    for (const it of items) { scene.nodes.delete(it.id); it.node.el.remove(); scene.scene.remove(it.node.group); }
    scene._pickables = [];
    items = [];
    const n = Math.min(cards.length, 12);
    for (let i = 0; i < n; i++) {
      const c = cards[i];
      const sel = String(c.id) === String(selectedId);
      const row = Math.floor(i / 6);
      const pos = sel ? [0, 0.16, 1.3] : arcPos(i, row);
      const node = scene.addNode({
        id: String(c.id),
        // shelf pods wear a number tag; the company surfaces on hover and on
        // the inspection platform (and always in the cards below)
        label: sel ? `#${i + 1} ${c.company}` : `#${i + 1}`,
        sub: `${sel ? "" : c.company + " · "}score ${c.fit_score ?? "—"} · ${c.source_label || c.source}`,
        pos, kind: "pod",
        scale: sel ? 1.5 : 0.85 + 0.35 * ((c.fit_score || 0) / 100),
        focusRadius: 4.2, chrome: sel ? "full" : "auto",
      });
      node.labelOffset = sel ? 1.1 : (i % 2 ? 0.98 : 0.62) + (row ? 0.26 : 0);  // four distinct tag heights
      node.quiet = !sel;                       // shelf attention lives in the glyph until hover
      scene.setNodeState(String(c.id), {
        state: c.read_first ? "blocked" : "idle",
        line: sel ? (c.role || "") : (c.read_first ? "gate closed — read the posting first" : "waiting"),
        metric: sel ? [c.cover_letter_path ? "letter attached" : "no letter",
                      `${(c.screening_answers || []).length} answers`].join(" · ") : "",
      });
      items.push({ id: String(c.id), node });
    }
    if (cards.length > n) scene.setNodeState("you", { metric: `+${cards.length - n} more in backlog` });
    scene.requestRender();
  }
  function applyEvent(e) {
    if (e.type === "submission_sent" && e.stage === "ui") scene.firePacket("release", { color: PAL.ok });
  }
  return { scene, setData, applyEvent };
}


/* ══════════════ INBOX — Signal Intelligence Array ══════════════ */

/* class colors: red stays reserved for system failures, so rejections are
   warm bronze records, not alarms; green marks real wins only */
const CLS_STYLE = {
  confirmation: { color: PAL.silver, label: "Confirmations" },
  rejection: { color: PAL.record, label: "Rejections" },
  interview: { color: PAL.ok, label: "Interviews" },
  offer: { color: PAL.ok, label: "Offers" },
  action_needed: { color: PAL.warn, label: "Action needed" },
  noise: { color: PAL.idle, label: "Noise" },
};

export function buildInbox(host, { onPickClass }) {
  const scene = new OpsScene(host, {
    ariaLabel: "Signal intelligence array: employer messages arriving from outside the trusted boundary, classified into bins.",
    camera: { radius: 8, phi: 0.95, theta: 0, target: [0, 0.3, 0.4], maxTheta: 0.9, panLimit: 1 },
    onSelect: onPickClass,
  });
  if (!scene.ok) return null;
  scene.addZone({ label: "Untrusted exterior", x: 0, z: -2.6, w: 8, d: 1.8 });
  scene.addZone({ label: "Receiver", x: 0, z: 0.1, w: 2.4, d: 2 });
  const wallL = build.wall(2.8); wallL.position.set(-2.4, 0, -1.5);
  const wallR = build.wall(2.8); wallR.position.set(2.4, 0, -1.5);
  scene.scene.add(wallL, wallR);

  // telemetry receiver room: paneled floor, routing channels from the
  // receiver to every classification bay, aperture wall behind the exterior
  scene.scene.add(env.floorRect(13.5, 9.5, { border: 1.8 }));
  const apWall = env.wallArc(9.8, Math.PI * 0.33, Math.PI * 0.67, { h: 1.9, slits: 4 });
  apWall.position.z = 3.4;                     // curve sits far behind the boundary
  scene.scene.add(apWall);
  for (let i = 0; i < 6; i++)
    scene.scene.add(env.conduit(0, 0.5, -3.4 + i * 1.36, 2.3, { lit: 0.07 }));
  const rvPool = env.poolLight(1.7);
  rvPool.position.set(0, 0.012, 0.1);
  scene.scene.add(rvPool);
  for (const [x, z, seed] of [[-6.6, -3.4, 3], [6.6, -3.2, 12]]) {
    const s = env.silhouette(seed);
    s.position.set(x, 0, z);
    s.rotation.y = x > 0 ? -1.2 : 1.2;
    scene.scene.add(s);
  }
  const recvN = scene.addNode({ id: "recv", label: "Inbox reader", sub: "classifier", pos: [0, 0.05, 0.1], kind: "antenna", scale: 1.15 });
  recvN.labelOffset = 1.55;
  scene.addNode({ id: "ext", label: "Employer mail", sub: "outside the boundary", pos: [0, 0.05, -2.6], kind: "pylon", scale: 0.9 });
  scene.addNode({ id: "you", label: "You", sub: "priority path", pos: [4.4, 0.05, 2.55], kind: "pylon", scale: 0.85 });
  scene.addPath("in", [[0, 0.5, -2.6], [0, 0.6, 0.1]], { arc: 0.7 });
  const order = ["noise", "rejection", "confirmation", "action_needed", "offer", "interview"];
  order.forEach((cls, i) => {
    const s = CLS_STYLE[cls];
    const x = -3.4 + i * 1.36;
    const geo = { interview: () => new THREE.ConeGeometry(0.16, 0.3, 5), offer: () => new THREE.ConeGeometry(0.16, 0.3, 5),
      action_needed: () => new THREE.OctahedronGeometry(0.17, 0), confirmation: () => new THREE.BoxGeometry(0.24, 0.24, 0.24),
      rejection: () => new THREE.TetrahedronGeometry(0.2, 0), noise: () => new THREE.SphereGeometry(0.13, 8, 6) }[cls]();
    // a real classification bay: chamfered pedestal, collection tray with a
    // slot, backboard with the class glyph mounted on it, small status lamp
    const g = new THREE.Group();
    const base = build.bevelBox(0.62, 0.12, 0.5, new THREE.MeshStandardMaterial({ color: PAL.charcoal, roughness: 0.7, metalness: 0.25 }), 0.03);
    const tray = build.bevelBox(0.5, 0.05, 0.34, new THREE.MeshStandardMaterial({ color: PAL.metalDark, roughness: 0.4, metalness: 0.75 }), 0.015);
    tray.position.y = 0.14;
    const slot = new THREE.Mesh(new THREE.BoxGeometry(0.36, 0.02, 0.1),
      new THREE.MeshStandardMaterial({ color: 0x0d0e10, roughness: 0.9 }));
    slot.position.set(0, 0.175, 0.06);
    const board = build.bevelBox(0.46, 0.5, 0.05, new THREE.MeshStandardMaterial({ color: 0x2a2d33, roughness: 0.6, metalness: 0.35 }), 0.02);
    board.position.set(0, 0.42, -0.19);
    const mark = new THREE.Mesh(geo, new THREE.MeshStandardMaterial({
      color: s.color, emissive: s.color, emissiveIntensity: cls === "noise" ? 0.05 : 0.55, roughness: 0.5 }));
    mark.scale.setScalar(1.0);
    mark.position.set(0, 0.46, -0.14);
    const lamp = new THREE.Mesh(new THREE.SphereGeometry(0.03, 8, 6), new THREE.MeshStandardMaterial({
      color: 0x2a2d33, emissive: s.color, emissiveIntensity: 0.25, roughness: 0.5 }));
    lamp.position.set(0.18, 0.64, -0.16);
    g.add(base, tray, slot, board, mark, lamp);
    const node = scene.addNode({ id: cls, label: s.label, sub: "", pos: [x, 0.05, 2.6], kind: "pylon", scale: 0.0001 });
    node.group.add(g);                                    // replace pylon visual
    node.group.scale.setScalar(cls === "noise" ? 0.95 : 1.18);
    node.labelOffset = 0.8;
    scene.addPath("bin_" + cls, [[0, 0.5, 0.1], [x, 0.4, 2.6]], { arc: 0.5 });
  });
  scene.addPath("prio", [[3.4, 0.4, 2.6], [4.4, 0.5, 2.55]], { arc: 0.4 });

  function setData(counts) {
    for (const cls of order)
      scene.setNodeState(cls, { state: (cls === "interview" || cls === "offer") && counts[cls] ? "ok"
        : cls === "action_needed" && counts[cls] ? "blocked" : "idle",
        metric: `${counts[cls] || 0}` });
    scene.requestRender();
  }
  function applyEvent(e) {
    if (e.type !== "email_classified") return;
    scene.setPathState("in", "in");
    scene.firePacket("in", { color: PAL.silver });
    const cls = e.cls && CLS_STYLE[e.cls] ? e.cls : "noise";
    setTimeout(() => scene.firePacket("bin_" + cls, { color: CLS_STYLE[cls].color }), 900);
    if (cls === "interview" || cls === "action_needed")
      setTimeout(() => scene.firePacket("prio", { color: PAL.warn }), 1800);
  }
  return { scene, setData, applyEvent };
}

/* ══════════════ APPLICATIONS — Dimensional Transit Facility (v3) ══════════
   A real transit hall: every tracked job is a capsule on the belt, each
   stage has its own physically distinct gate (intake mast, holding clamps,
   stamp arch, scanner ring, interview posts, offer beacon), platforms
   shorten as the funnel narrows, guide rails run the length of the belt,
   and closed records rest in a recessed dormant channel up front. */

const STAGES = ["discovered", "queued", "applied", "screening", "interview", "offer", "rejected", "ghosted", "skipped"];

function stageGate(kind) {
  const g = new THREE.Group();
  const mS = () => new THREE.MeshStandardMaterial({ color: PAL.structural, roughness: 0.7, metalness: 0.3 });
  const mM = () => new THREE.MeshStandardMaterial({ color: PAL.metal, roughness: 0.35, metalness: 0.85 });
  const mE = (c, i = 0.5) => new THREE.MeshStandardMaterial({ color: 0x2a2d33, emissive: c, emissiveIntensity: i, roughness: 0.5 });
  const post = (x, h = 0.9) => {
    const p = build.bevelBox(0.12, h, 0.16, mS(), 0.025);
    p.position.set(x, h / 2, 0);
    return p;
  };
  switch (kind) {
    case "discovered": {                       // intake mast: antenna over the mouth
      g.add(post(-0.8, 0.7), post(0.8, 0.7));
      const mast = new THREE.Mesh(new THREE.CylinderGeometry(0.025, 0.04, 0.7, 6), mM());
      mast.position.set(-0.8, 1.05, 0);
      const cross = new THREE.Mesh(new THREE.BoxGeometry(0.4, 0.03, 0.03), mM());
      cross.position.set(-0.8, 1.32, 0);
      g.add(mast, cross);
      break;
    }
    case "queued": {                           // holding clamps + amber hold bar
      g.add(post(-0.8, 0.85), post(0.8, 0.85));
      const bar = new THREE.Mesh(new THREE.BoxGeometry(1.6, 0.05, 0.06), mE(PAL.warn, 0.35));
      bar.position.y = 0.8;
      const clampL = new THREE.Mesh(new THREE.BoxGeometry(0.08, 0.3, 0.22), mM());
      clampL.position.set(-0.55, 0.35, 0);
      const clampR = clampL.clone(); clampR.position.x = 0.55;
      g.add(bar, clampL, clampR);
      break;
    }
    case "applied": {                          // stamp arch: a seal hangs over the belt
      g.add(post(-0.8, 1.0), post(0.8, 1.0));
      const beam = build.bevelBox(1.75, 0.12, 0.2, mS(), 0.03);
      beam.position.y = 1.02;
      const stamp = new THREE.Mesh(new THREE.CylinderGeometry(0.1, 0.13, 0.14, 12), mE(PAL.ember, 0.5));
      stamp.position.y = 0.78;
      g.add(beam, stamp);
      break;
    }
    case "screening": {                        // scanner ring: jobs pass through inspection
      const ring = new THREE.Mesh(new THREE.TorusGeometry(0.55, 0.05, 10, 32), mM());
      ring.position.y = 0.62;
      const scan = new THREE.Mesh(new THREE.TorusGeometry(0.44, 0.018, 8, 32), mE(PAL.silver, 0.35));
      scan.position.y = 0.62;
      const foot = build.bevelBox(0.5, 0.1, 0.4, mS(), 0.03);
      foot.position.y = 0.05;
      g.add(ring, scan, foot);
      break;
    }
    case "interview": {                        // twin posts, green appointment lamp
      g.add(post(-0.7, 1.05), post(0.7, 1.05));
      const lamp = new THREE.Mesh(new THREE.BoxGeometry(1.35, 0.06, 0.08), mE(PAL.ok, 0.4));
      lamp.position.y = 1.04;
      g.add(lamp);
      break;
    }
    case "offer": {                            // beacon arch: the good ending
      const arch = new THREE.Mesh(new THREE.TorusGeometry(0.7, 0.06, 10, 28, Math.PI), mM());
      arch.position.y = 0.25;
      const beacon = new THREE.Mesh(new THREE.OctahedronGeometry(0.11, 0), mE(PAL.ok, 0.55));
      beacon.position.y = 1.05;
      g.add(arch, beacon);
      break;
    }
  }
  return g;
}

export function buildPipeline(host, { onStage }) {
  const scene = new OpsScene(host, {
    ariaLabel: "Dimensional transit facility: every tracked job is a capsule at its verified stage; each stage gate is a different machine.",
    camera: { radius: 11.6, phi: 0.98, theta: 0, target: [0.4, 0.3, 0.2], maxTheta: 1, panLimit: 2.2 },
    shadowBounds: 10,
    onSelect: onStage,
  });
  if (!scene.ok) return null;

  // transit hall: long floor, guide rails flanking the belt, silhouettes
  scene.scene.add(env.floorRect(17.5, 11, { border: 2 }));
  const railF = build.wall(13.4, { h: 0.28 });
  railF.position.set(-0.2, 0, 1.05);
  const railB = build.wall(13.4, { h: 0.28 });
  railB.position.set(-0.2, 0, -3.0);
  scene.scene.add(railF, railB);
  scene.scene.add(env.conduit(-6.2, -0.4, 6.2, -0.4, { lit: 0.09 }));
  for (const [x, z, seed] of [[-8.4, -4.2, 5], [8.6, -3.8, 10], [8.2, 3.6, 7]]) {
    const s = env.silhouette(seed);
    s.position.set(x, 0, z);
    s.rotation.y = x > 0 ? -1.1 : 1.1;
    scene.scene.add(s);
  }
  const winPool = env.poolLight(1.9);
  winPool.position.set(5.4, 0.012, -0.4);
  scene.scene.add(winPool);

  const xs = {};
  const active = ["discovered", "queued", "applied", "screening", "interview", "offer"];
  const depth = { discovered: 3.1, queued: 2.8, applied: 2.6, screening: 2.3, interview: 2.0, offer: 1.8 };
  active.forEach((s, i) => {
    const x = -5.4 + i * 2.16;
    xs[s] = x;
    scene.addZone({ x, z: -0.4, w: 1.9, d: depth[s] });
    const gate = stageGate(s);
    gate.position.set(x - 1.08, 0.02, -0.4);
    gate.rotation.y = Math.PI / 2;
    scene.scene.add(gate);
    scene.addNode({ id: s, label: s[0].toUpperCase() + s.slice(1), sub: "", pos: [x, 0.05, -1.95], kind: "pylon", scale: 0.62, focusRadius: 4.5 });
  });
  scene.addZone({ label: "Dormant / closed", x: -1.4, z: 2.6, w: 9.6, d: 1.8, y: -0.03 });
  ["rejected", "ghosted", "skipped"].forEach((s, i) => {
    const x = -4.2 + i * 2.8;
    xs[s] = x;
    scene.addNode({ id: s, label: s[0].toUpperCase() + s.slice(1), sub: "", pos: [x, 0.02, 3.2], kind: "pylon", scale: 0.5 });
  });
  for (let i = 0; i < active.length - 1; i++)
    scene.addPath("t" + i, [[xs[active[i]], 0.35, -0.4], [xs[active[i + 1]], 0.35, -0.4]], { arc: 0.45 });

  let inst = null;
  function setData(counts) {
    if (inst) { scene.scene.remove(inst); inst.geometry.dispose(); inst.material.dispose(); }
    const CAP = 40;
    const total = STAGES.reduce((a, s) => a + Math.min(counts[s] || 0, CAP), 0);
    inst = new THREE.InstancedMesh(new THREE.CapsuleGeometry(0.055, 0.1, 3, 8),
      new THREE.MeshStandardMaterial({ color: PAL.metal, roughness: 0.45, metalness: 0.55 }), Math.max(total, 1));
    inst.castShadow = true;
    const m4 = new THREE.Matrix4();
    let k = 0;
    for (const s of STAGES) {
      const n = Math.min(counts[s] || 0, CAP);
      const dormant = !active.includes(s);
      for (let i = 0; i < n; i++) {
        const col = i % 8, row = Math.floor(i / 8);
        m4.makeRotationX(Math.PI / 2);
        m4.setPosition(xs[s] - 0.62 + col * 0.18, dormant ? 0.09 : 0.12, (dormant ? 2.4 : -1.25) + row * 0.2);
        inst.setMatrixAt(k++, m4);
      }
      scene.setNodeState(s, { metric: String(counts[s] || 0),
        state: (s === "interview" || s === "offer") && counts[s] ? "ok" : "idle",
        line: (counts[s] || 0) > CAP ? `showing ${CAP} of ${counts[s]}` : "" });
    }
    inst.count = k || 1;
    inst.instanceMatrix.needsUpdate = true;
    scene.scene.add(inst);
    scene.requestRender();
  }
  function applyEvent(e) {
    if (e.type === "job_queued") scene.firePacket("t0", {});
    if (e.type === "submission_sent") scene.firePacket("t1", {});
  }
  return { scene, setData, applyEvent };
}

/* ══════════════ SUBMISSIONS — Secure Egress & Launch Control ══════════════ */

export function buildEgress(host, { onBay }) {
  const scene = new OpsScene(host, {
    ariaLabel: "Secure egress: prepared application packets in their real bays, and the controlled outbound gateway.",
    camera: { radius: 8.6, phi: 0.98, theta: -0.05, target: [0.4, 0.3, 0], maxTheta: 0.95, panLimit: 1.4 },
    onSelect: onBay,
  });
  if (!scene.ok) return null;

  // secure launch dock: floor, gantry frame over the gateway, outbound
  // chevrons through the wall gap, back wall, background machinery
  scene.scene.add(env.floorRect(14.5, 9.5, { border: 1.8 }));
  const dockWall = env.wallArc(9.6, Math.PI * 0.36, Math.PI * 0.72, { h: 1.9, slits: 4 });
  dockWall.position.set(-1.2, 0, 3.2);
  scene.scene.add(dockWall);
  const gantry = new THREE.Group();
  const gpostL = build.bevelBox(0.14, 1.7, 0.2, new THREE.MeshStandardMaterial({ color: PAL.structural, roughness: 0.7, metalness: 0.3 }), 0.03);
  gpostL.position.set(3.2 - 1.35, 0.85, -0.6);
  const gpostR = gpostL.clone(); gpostR.position.x = 3.2 + 1.35;
  const gbeam = build.bevelBox(2.9, 0.14, 0.24, new THREE.MeshStandardMaterial({ color: PAL.metalDark, roughness: 0.4, metalness: 0.8 }), 0.03);
  gbeam.position.set(3.2, 1.72, -0.6);
  const glamp = new THREE.Mesh(new THREE.BoxGeometry(0.5, 0.05, 0.08),
    new THREE.MeshStandardMaterial({ color: 0x2a2d33, emissive: PAL.ember, emissiveIntensity: 0.3 }));
  glamp.position.set(3.2, 1.63, -0.48);
  gantry.add(gpostL, gpostR, gbeam, glamp);
  scene.scene.add(gantry);
  const outChev = env.chevrons(3);
  outChev.position.set(4.6, 0, -0.75);
  scene.scene.add(outChev);
  const gwPool = env.poolLight(1.8);
  gwPool.position.set(3.2, 0.012, -0.6);
  scene.scene.add(gwPool);
  for (const [x, z, seed] of [[-6.8, -3.2, 6], [-6.4, 3.0, 11]]) {
    const s = env.silhouette(seed);
    s.position.set(x, 0, z);
    s.rotation.y = 1.2;
    scene.scene.add(s);
  }

  // prepared ≠ success: the ready bay is silver; amber only where you're needed
  const bays = [["ready", "Ready", -3.4, PAL.silver], ["handoff", "Handoff to you", -1.2, PAL.warn],
                ["skip", "Skipped", 1.0, PAL.idle]];
  for (const [id, label, x, color] of bays) {
    scene.addZone({ x, z: 0.9, w: 1.9, d: 2 });
    const node = scene.addNode({ id, label, sub: "", pos: [x, 0.05, 0.9], kind: "chamber", scale: 0.8 });
    node.group.children.forEach(ch => { if (ch.material && ch.material.emissive) { ch.material.color.setHex(color); ch.material.emissive.setHex(color); } });
  }
  scene.addZone({ label: "Review hold", x: -3.4, z: -1.8, w: 1.9, d: 1.8 });
  scene.addNode({ id: "review", label: "Review hold", sub: "safety ramp", pos: [-3.4, 0.05, -1.8], kind: "chamber", scale: 0.8 });
  scene.addZone({ label: "Egress gateway", x: 3.2, z: -0.6, w: 2.2, d: 2.4 });
  scene.addNode({ id: "gateway", label: "Egress gateway", sub: "submission head", pos: [3.2, 0.05, -0.6], kind: "gateway", scale: 1.05, focusRadius: 4 });
  const atsN = scene.addNode({ id: "ats", label: "Employer ATS", sub: "", pos: [6.2, 0.05, -0.9], kind: "terminals", scale: 0.85 });
  atsN.group.rotation.y = 0.5;                 // faces the gateway it receives from
  scene.addPath("launch", [[-3.4, 0.4, 0.9], [3.2, 0.6, -0.6]], { arc: 0.8 });
  scene.setPathState("launch", "today");       // the launch ramp reads as a ramp
  scene.addPath("out", [[3.2, 0.5, -0.6], [6.2, 0.6, -0.9]], { arc: 0.7 });
  scene.addPath("ack", [[6.2, 0.5, -0.9], [3.2, 0.7, -0.6]], { arc: 1.2 });
  scene.addPath("toyou", [[-1.2, 0.4, 0.9], [-1.2, 0.5, 3.0]], { arc: 0.5 });

  function setData({ counts, auto }) {
    scene.setNodeState("ready", { metric: String(counts.ready || 0), state: counts.ready ? "ok" : "idle" });
    scene.setNodeState("handoff", { metric: String(counts.handoff || 0), state: counts.handoff ? "blocked" : "idle" });
    scene.setNodeState("skip", { metric: String(counts.skip || 0) });
    scene.setNodeState("review", {
      state: auto.awaiting_review ? "blocked" : "idle",
      line: auto.awaiting_review ? "amber gate locked — your review" : "clear",
      metric: `${auto.live_count}/${auto.verify_first_n} live sends` });
    scene.setNodeState("gateway", {
      state: auto.awaiting_review ? "blocked" : auto.enabled ? "ok" : "idle",
      line: auto.enabled ? (auto.dry_run ? "dry run" : auto.awaiting_review ? "HOLDING" : "armed") : "off" });
    scene.requestRender();
  }
  function applyEvent(e) {
    if (e.type === "submission_sent") { scene.firePacket("launch", {}); setTimeout(() => scene.firePacket("out", {}), 1300); }
    if (e.type === "submission_handoff") scene.firePacket("toyou", { color: PAL.warn });
    if (e.type === "submission_waiting_review") scene.setNodeState("review", { state: "blocked", line: "amber gate locked — your review" });
    if (e.type === "email_classified") scene.firePacket("ack", { color: PAL.silver });
  }
  return { scene, setData, applyEvent };
}

/* ══════════════ ANSWERS — Encrypted Knowledge Vault ══════════════ */

export function buildVault(host, { onSector }) {
  const scene = new OpsScene(host, {
    ariaLabel: "Knowledge vault: the answer bank's sections as vault sectors around the secure core.",
    camera: { radius: 8.6, phi: 0.78, theta: 0, target: [0, 0.25, 0.15], maxTheta: 3.2, panLimit: 0.8 },
    onSelect: onSector,
  });
  if (!scene.ok) return null;
  const core = new THREE.Mesh(new THREE.CylinderGeometry(0.55, 0.65, 0.9, 24),
    new THREE.MeshStandardMaterial({ color: PAL.charcoal, metalness: 0.5, roughness: 0.45 }));
  core.position.y = 0.45;
  const coreRing = new THREE.Mesh(new THREE.TorusGeometry(0.7, 0.025, 8, 48),
    new THREE.MeshStandardMaterial({ color: PAL.emberDeep, emissive: PAL.ember, emissiveIntensity: 0.4 }));
  coreRing.rotation.x = Math.PI / 2; coreRing.position.y = 0.9;
  scene.scene.add(core, coreRing);
  scene.addZone({ label: "Secure knowledge core", x: 0, z: 0, w: 7.2, d: 7.2 });

  // encrypted archive chamber: ring floor, near-closed wall, index pool
  scene.scene.add(env.floorDisc(6.4, { seams: 12, channelR: 4.4, apron: 2.0 }));
  scene.scene.add(env.wallArc(6.7, 0.35, Math.PI * 2 - 0.35, { h: 1.8, slits: 8 }));
  scene.scene.add(env.poolLight(1.9));
  const idx = new THREE.Mesh(new THREE.CylinderGeometry(0.05, 0.05, 1.35, 6),
    new THREE.MeshStandardMaterial({ color: PAL.metal, roughness: 0.35, metalness: 0.85 }));
  idx.position.y = 1.45;
  const idxTip = new THREE.Mesh(new THREE.OctahedronGeometry(0.09, 0),
    new THREE.MeshStandardMaterial({ color: 0x2a2d33, emissive: PAL.ember, emissiveIntensity: 0.45 }));
  idxTip.position.y = 2.2;
  scene.scene.add(idx, idxTip);

  let sectors = [];
  function setData(sections, { gapsOpen, recentFields }) {
    for (const s of sectors) { scene.nodes.delete(s.id); s.node.el.remove(); scene.scene.remove(s.node.group); }
    scene._pickables = [];
    sectors = [];
    const n = sections.length;
    sections.forEach((sec, i) => {
      const a = -Math.PI * 0.92 + (i / Math.max(1, n - 1)) * Math.PI * 1.84;
      const R = 2.7;
      const node = scene.addNode({ id: sec.key, label: `§${sec.key}`, sub: sec.title,
        pos: [Math.sin(a) * R, 0.05, Math.cos(a) * R], kind: "vault", scale: 0.62, focusRadius: 3.4 });
      node.group.rotation.y = a + Math.PI;
      node.labelOffset = 0.75;
      const edited = (recentFields || []).some(f => (sec.rows || []).some(r => r.field === f));
      const state = sec.key === "M" && gapsOpen ? "blocked" : edited ? "run" : "ok";
      scene.setNodeState(sec.key, {
        state,
        line: [sec.attest ? "attestation band" : "", sec.sensitive ? "privacy lock" : "",
               edited ? "recently edited" : ""].filter(Boolean).join(" · ") || (sec.editable ? "sealed · healthy" : "reference"),
        metric: sec.rows && sec.rows.length ? `${sec.rows.length} answers` : "",
      });
      if (sec.attest) {
        const band = new THREE.Mesh(new THREE.BoxGeometry(0.66, 0.05, 0.56),
          new THREE.MeshStandardMaterial({ color: PAL.metal, metalness: 0.9, roughness: 0.25 }));
        band.position.y = 0.42;
        node.group.add(band);
      }
      if (sec.sensitive) {
        const lock = new THREE.Mesh(new THREE.TorusGeometry(0.08, 0.025, 8, 18, Math.PI),
          new THREE.MeshStandardMaterial({ color: PAL.warn, emissive: PAL.warn, emissiveIntensity: 0.3 }));
        lock.position.set(0, 0.62, 0.2);
        node.group.add(lock);
      }
      sectors.push({ id: sec.key, node });
    });
    if (gapsOpen) {
      scene.setNodeState("M", { state: "blocked", line: `${gapsOpen} open gap${gapsOpen > 1 ? "s" : ""} — amber breach`, metric: "" });
    }
    scene.requestRender();
  }
  return { scene, setData, applyEvent: () => {} };
}

/* ══════════════ CHAT — Copilot core ══════════════ */

export function buildCopilot(host) {
  const scene = new OpsScene(host, {
    ariaLabel: "Copilot core: the chat agent's live state.",
    camera: { radius: 3.4, phi: 1.0, theta: 0.3, target: [0, 0.35, 0], maxTheta: 3.2, panLimit: 0.2 },
  });
  if (!scene.ok) return null;
  // focused operator alcove: small dais, curved backdrop, one pool of light
  scene.scene.add(env.floorDisc(2.5, { seams: 6, apron: 0.9 }));
  scene.scene.add(env.wallArc(2.65, 0.5, Math.PI - 0.5, { h: 1.25, slits: 3 }));
  scene.scene.add(env.poolLight(1.25));
  scene.addNode({ id: "copilot", label: "Copilot", sub: "", pos: [0, 0, 0], kind: "node", scale: 1.1, focusRadius: 3 });
  function setState({ busy, proposals, error }) {
    scene.setNodeState("copilot", {
      state: error ? "fail" : proposals ? "blocked" : busy ? "run" : "ok",
      line: error ? "error" : proposals ? `${proposals} proposal${proposals > 1 ? "s" : ""} await your approval`
        : busy ? "processing…" : "listening",
    });
  }
  return { scene, setState, applyEvent: () => {} };
}
