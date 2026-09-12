/* JobBot ops3d v2 — the shared spatial engine (session 15 refinement).
   Semantic machinery: every object is built to resemble its function, with
   mechanism animations that run ONLY for real states and events. Crimson is
   the single energy accent (orange supports, silver is inbound, green is
   success-only, red is failure-only + glyph). Neutral charcoal and brushed
   metal replace the muddy brown. Labels are DOM twins with auto priority
   (quiet objects wear a compact tag; active/warning/selected expand), a
   global collision solver, and glyphed states. Camera: clamped orbit,
   presets, context-preserving focus. Rendering stays on-demand; reduced
   motion, low power, disposal, and __ops3d hooks carry over. */

import * as THREE from "three";

export const PAL = {
  void: 0x0b0b0a, structural: 0x262a30, charcoal: 0x2b2e34, raise: 0x2f3236,
  metal: 0x9aa0a6, metalDark: 0x565b61, ink: 0xf2efe9,
  ember: 0xf08a4b, emberHot: 0xffb27a, emberDeep: 0xd96f2e, emberDark: 0xa8541e,
  record: 0x9c6b3a,
  silver: 0xc9cdd3,
  ok: 0x0ca30c, warn: 0xfab219, fail: 0xe23b2e, idle: 0x6a6f75,
  page: 0xe9e5da,
};

export const reducedMotion = () => matchMedia("(prefers-reduced-motion: reduce)").matches;
const LP_KEY = "jb-3d-lowpower";
export const lowPowerPref = () => { try { return localStorage.getItem(LP_KEY) === "1"; } catch (e) { return false; } };
export const setLowPowerPref = v => { try { localStorage.setItem(LP_KEY, v ? "1" : ""); } catch (e) {} };
export function supportsWebGL() {
  try { const c = document.createElement("canvas"); return !!(c.getContext("webgl2") || c.getContext("webgl")); }
  catch (e) { return false; }
}

/* ---------------- event feed (unchanged contract) ---------------- */

export class EventFeed {
  constructor({ onEvent, onMode } = {}) {
    this.onEvent = onEvent || (() => {});
    this.onMode = onMode || (() => {});
    this.mode = "paused";
    this.lastId = 0;
    this._es = null; this._poll = null; this._replayTimer = null;
  }
  _setMode(m) { this.mode = m; this.onMode(m); }
  async live() {
    this.stopAll();
    this._setMode("live");
    try {
      const d = await fetch("/api/events?limit=1").then(r => r.json());
      this.lastId = d.last_id || 0;
    } catch (e) { /* stream skips backlog itself */ }
    if ("EventSource" in window) {
      try {
        this._es = new EventSource(`/api/events/stream?since_id=${this.lastId}`);
        this._es.onmessage = ev => {
          try {
            const e = JSON.parse(ev.data);
            if (e.id <= this.lastId) return;
            this.lastId = e.id;
            if (this.mode === "live") this.onEvent(e, { live: true });
          } catch (err) { /* ignore malformed */ }
        };
        this._es.onerror = () => {};
        return;
      } catch (e) { /* fall to polling */ }
    }
    this._poll = setInterval(async () => {
      if (this.mode !== "live") return;
      try {
        const d = await fetch(`/api/events?since_id=${this.lastId}`).then(r => r.json());
        for (const e of d.events) { this.lastId = Math.max(this.lastId, e.id); this.onEvent(e, { live: true }); }
      } catch (e) {}
    }, 3000);
  }
  replay(events, { speed = 2 } = {}) {
    this.stopAll();
    this._setMode("replay");
    this._replay = { events, i: 0, speed, playing: true };
    this._replayStep();
  }
  _replayStep() {
    const r = this._replay;
    if (!r || this.mode !== "replay" || !r.playing) return;
    if (r.i >= r.events.length) { r.playing = false; this.onMode("replay-done"); return; }
    this.onEvent(r.events[r.i++], { replay: true, index: r.i, total: r.events.length });
    this._replayTimer = setTimeout(() => this._replayStep(), 1000 / r.speed);
  }
  replaySeek(i) { if (this._replay) this._replay.i = Math.max(0, Math.min(i, this._replay.events.length)); }
  replayPause() { if (this._replay) { this._replay.playing = false; clearTimeout(this._replayTimer); } }
  replayPlay() { if (this._replay && !this._replay.playing) { this._replay.playing = true; this._replayStep(); } }
  pause() { this._setMode("paused"); }
  resumeLive() { this.live(); }
  stopAll() {
    if (this._es) { this._es.close(); this._es = null; }
    if (this._poll) { clearInterval(this._poll); this._poll = null; }
    clearTimeout(this._replayTimer);
    this._replay = null;
  }
  dispose() { this.stopAll(); this._setMode("paused"); }
}

/* ---------------- procedural surface detail (no downloads) ----------------
   Two tiny shared CanvasTextures give metal and floors real surface response:
   a horizontal brushed-grain roughness map and a floor panel-line map. */

function canvasTex(size, draw) {
  const c = document.createElement("canvas");
  c.width = c.height = size;
  const x = c.getContext("2d");
  draw(x, size);
  const t = new THREE.CanvasTexture(c);
  t.wrapS = t.wrapT = THREE.RepeatWrapping;
  return t;
}
let _texBrushed = null, _texPanels = null;
const texBrushed = () => _texBrushed ||= canvasTex(128, (x, s) => {
  x.fillStyle = "#8a8a8a"; x.fillRect(0, 0, s, s);
  for (let i = 0; i < 640; i++) {
    const y = Math.random() * s, w = 20 + Math.random() * 90, v = 110 + Math.random() * 70 | 0;
    x.strokeStyle = `rgb(${v},${v},${v})`; x.lineWidth = 0.6;
    x.beginPath(); x.moveTo(Math.random() * s - 40, y); x.lineTo(Math.random() * s - 40 + w, y); x.stroke();
  }
});
const texPanels = () => _texPanels ||= canvasTex(256, (x, s) => {
  x.fillStyle = "#9a9a9a"; x.fillRect(0, 0, s, s);
  x.strokeStyle = "#6e6e6e"; x.lineWidth = 2;
  for (const k of [0, 0.5]) {
    x.strokeRect(1 + k * s, 1, s / 2 - 2, s / 2 - 2);
    x.strokeRect(1 + (0.5 - k) * s, 1 + s / 2, s / 2 - 2, s / 2 - 2);
  }
  x.strokeStyle = "#7c7c7c"; x.lineWidth = 1;
  for (let i = 0; i < 10; i++) {
    x.beginPath(); x.moveTo(Math.random() * s, 0); x.lineTo(Math.random() * s, s); x.stroke();
  }
});

/* ---------------- materials (distinct physical roles) ---------------- */

const mstruct = (c = PAL.structural) => new THREE.MeshStandardMaterial({
  color: c, roughness: 0.78, metalness: 0.22, roughnessMap: texBrushed() });
const mmetal = (c = PAL.metal) => new THREE.MeshStandardMaterial({
  color: c, roughness: 0.34, metalness: 0.88, roughnessMap: texBrushed() });
const mdark = () => new THREE.MeshStandardMaterial({ color: PAL.metalDark, roughness: 0.45, metalness: 0.7, roughnessMap: texBrushed() });
const mtrim = () => new THREE.MeshStandardMaterial({ color: 0x17181a, roughness: 0.92, metalness: 0.05 });  // rubber/protective trim
const mfloor = (c = 0x1f2227) => new THREE.MeshStandardMaterial({
  color: c, roughness: 0.9, metalness: 0.12, roughnessMap: texPanels() });
const memiss = (c, i = 0.6, base = null) => new THREE.MeshStandardMaterial({
  color: base ?? c, roughness: 0.5, metalness: 0.2, emissive: c, emissiveIntensity: i });
const mglass = (c = 0x14161a, o = 0.4) => new THREE.MeshStandardMaterial({
  color: c, transparent: true, opacity: o, roughness: 0.2, metalness: 0.1, depthWrite: false });
const mpage = () => memiss(0x8f8a7d, 0.12, PAL.page);
const mmatte = (c = 0x14161a) => new THREE.MeshStandardMaterial({ color: c, roughness: 0.95, metalness: 0.1 });  // background masses

const M = (geo, mat) => new THREE.Mesh(geo, mat);
const box = (w, h, d, mat) => M(new THREE.BoxGeometry(w, h, d), mat);
const cyl = (rt, rb, h, s, mat) => M(new THREE.CylinderGeometry(rt, rb, h, s), mat);
const torus = (r, t, mat, arc = Math.PI * 2) => M(new THREE.TorusGeometry(r, t, 10, 48, arc), mat);

/* chamfered slab via extrusion — machined equipment reads through bevels */
function bevelBox(w, h, d, mat, r = 0.03) {
  const s = new THREE.Shape();
  const hw = w / 2 - r, hd = d / 2 - r;
  s.moveTo(-hw, -hd - r); s.lineTo(hw, -hd - r); s.absarc(hw, -hd, r, -Math.PI / 2, 0);
  s.lineTo(hw + r, hd); s.absarc(hw, hd, r, 0, Math.PI / 2);
  s.lineTo(-hw, hd + r); s.absarc(-hw, hd, r, Math.PI / 2, Math.PI);
  s.lineTo(-hw - r, -hd); s.absarc(-hw, -hd, r, Math.PI, Math.PI * 1.5);
  const g = new THREE.ExtrudeGeometry(s, { depth: Math.max(0.01, h - 2 * r), bevelEnabled: true,
    bevelThickness: r, bevelSize: r, bevelSegments: 2, curveSegments: 4 });
  g.rotateX(-Math.PI / 2);
  g.translate(0, h / 2 - r, 0);
  return M(g, mat);
}

/* soft contact shadow: zero-light-cost grounding under every machine */
let _texBlob = null;
const texBlob = () => _texBlob ||= canvasTex(128, (x, s) => {
  const g = x.createRadialGradient(s / 2, s / 2, 4, s / 2, s / 2, s / 2);
  g.addColorStop(0, "rgba(0,0,0,0.55)"); g.addColorStop(0.7, "rgba(0,0,0,0.22)"); g.addColorStop(1, "rgba(0,0,0,0)");
  x.fillStyle = g; x.fillRect(0, 0, s, s);
});
function blobShadow(r = 0.6) {
  const m = M(new THREE.CircleGeometry(r, 24), new THREE.MeshBasicMaterial({
    map: texBlob(), transparent: true, depthWrite: false }));
  m.rotation.x = -Math.PI / 2;
  m.position.y = 0.006;
  m.renderOrder = -1;
  return m;
}

/* warm pool of light on the floor — purposeful, not a glow substitute */
let _texPool = null;
const texPool = () => _texPool ||= canvasTex(128, (x, s) => {
  const g = x.createRadialGradient(s / 2, s / 2, 2, s / 2, s / 2, s / 2);
  g.addColorStop(0, "rgba(255,178,122,0.16)"); g.addColorStop(0.6, "rgba(240,138,75,0.06)"); g.addColorStop(1, "rgba(0,0,0,0)");
  x.fillStyle = g; x.fillRect(0, 0, s, s);
});
function poolLight(r = 1.6) {
  const m = M(new THREE.CircleGeometry(r, 28), new THREE.MeshBasicMaterial({
    map: texPool(), transparent: true, depthWrite: false, blending: THREE.AdditiveBlending }));
  m.rotation.x = -Math.PI / 2;
  m.position.y = 0.008;
  m.renderOrder = -1;
  return m;
}

/* ---------------- semantic geometry library ---------------- */

export const build = {
  plate(w, d) {
    const g = new THREE.Group();
    const slab = bevelBox(w, 0.09, d, mstruct(PAL.charcoal), 0.03);
    const edge = box(w + 0.06, 0.025, d + 0.06, mmetal());
    edge.position.y = -0.035;
    g.add(slab, edge);
    return g;
  },
  wall(len, { h = 0.55 } = {}) {
    const g = new THREE.Group();
    const m = box(len, h, 0.035, mglass(0x3a4048, 0.3));
    m.position.y = h / 2;
    const edge = box(len, 0.02, 0.045, memiss(PAL.silver, 0.1, 0x565b61));
    edge.position.y = h;
    g.add(m, edge);
    return g;
  },
  platform() {
    const g = new THREE.Group();
    const disc = cyl(1.0, 1.12, 0.12, 28, mstruct(PAL.charcoal));
    disc.position.y = 0.06;
    const ring = torus(1.06, 0.022, memiss(PAL.warn, 0.5));
    ring.rotation.x = Math.PI / 2; ring.position.y = 0.13;
    g.add(disc, ring);
    return g;
  },

  /* Discovery — reconnaissance lens on an articulated arm over source glow */
  radar() {
    const g = new THREE.Group();
    g.add(cyl(0.3, 0.42, 0.22, 8, mstruct()));
    const post = cyl(0.05, 0.07, 0.75, 8, mmetal());
    post.position.y = 0.55;
    const arm = new THREE.Group();
    const armBar = box(0.62, 0.05, 0.06, mmetal());
    armBar.position.x = 0.28;
    const lens = new THREE.Group();
    const rim = torus(0.26, 0.045, memiss(PAL.silver, 0.1, 0x9aa0a6));
    const glass = cyl(0.22, 0.22, 0.015, 24, mglass(0x2a2e33, 0.5));
    glass.rotation.x = Math.PI / 2;
    const glow = cyl(0.2, 0.2, 0.008, 24, memiss(PAL.ember, 0.0, 0x1c1e22)); // lit only while scanning
    glow.rotation.x = Math.PI / 2; glow.position.z = -0.01;
    lens.add(rim, glass, glow);
    lens.position.set(0.58, 0, 0);
    lens.rotation.x = Math.PI / 2.4;
    arm.add(armBar, lens);
    arm.position.y = 0.9;
    g.add(post, arm);
    const handle = cyl(0.035, 0.035, 0.3, 8, mdark());
    handle.position.set(0.02, 0.9, 0); handle.rotation.z = Math.PI / 2;
    g.add(handle);
    g.userData.run = [{ o: arm, axis: "y", sp: 0.035 }];       // sweep only while running
    g.userData.hot = [glow.material];
    return g;
  },

  /* Scoring — calibrated gauge + converging comparison rings */
  rings() {
    const g = new THREE.Group();
    g.add(cyl(0.34, 0.44, 0.16, 8, mstruct()));
    const body = cyl(0.3, 0.34, 0.42, 20, mdark());
    body.position.y = 0.36;
    const dialBack = cyl(0.3, 0.3, 0.03, 24, mstruct(0x383c42));
    dialBack.rotation.x = Math.PI / 2; dialBack.position.set(0, 0.62, 0.16);
    const dial = torus(0.24, 0.02, memiss(PAL.silver, 0.3), Math.PI);  // calibrated arc
    dial.position.set(0, 0.62, 0.185); dial.rotation.z = Math.PI;
    const fill = torus(0.24, 0.024, memiss(PAL.ember, 0.8), Math.PI * 0.6);  // score fill
    fill.position.set(0, 0.62, 0.19); fill.rotation.z = Math.PI;
    const needle = box(0.02, 0.2, 0.02, memiss(PAL.emberHot, 0.9));
    needle.position.set(0, 0.7, 0.19);
    const rings = new THREE.Group();
    for (let i = 0; i < 2; i++) {
      const r = torus(0.4 + i * 0.09, 0.018, mmetal());
      r.rotation.x = Math.PI / 2;
      r.position.y = 0.18 + i * 0.1;
      rings.add(r);
    }
    g.add(body, dialBack, dial, fill, needle, rings);
    g.userData.run = [{ o: rings, axis: "y", sp: 0.05 }];
    g.userData.needle = needle;
    g.userData.scoreFill = fill;
    return g;
  },

  /* Letter writer — drafting table, page, mechanical stylus arm */
  forge() {
    const g = new THREE.Group();
    g.add(bevelBox(0.8, 0.16, 0.6, mstruct(), 0.035));
    const desk = bevelBox(0.74, 0.06, 0.5, mmetal(0x767c84), 0.02);
    desk.position.y = 0.26; desk.rotation.x = -0.18;
    const page = box(0.4, 0.012, 0.3, mpage());
    page.position.set(-0.05, 0.315, 0.02); page.rotation.x = -0.18;
    const lines = new THREE.Group();                            // written lines appear while writing
    for (let i = 0; i < 4; i++) {
      const ln = box(0.3, 0.006, 0.016, memiss(0x6a675e, 0.25, 0x55524a));
      ln.position.set(-0.06, 0.325, -0.08 + i * 0.055);
      ln.rotation.x = -0.18;
      ln.scale.x = 0.001;
      lines.add(ln);
    }
    const gantry = box(0.05, 0.34, 0.05, mmetal());
    gantry.position.set(0.34, 0.42, -0.12);
    const armH = box(0.5, 0.04, 0.05, mmetal());
    armH.position.set(0.1, 0.56, -0.12);
    const stylus = new THREE.Group();
    const shaft = cyl(0.02, 0.02, 0.22, 8, mdark());
    const nib = cyl(0.001, 0.03, 0.08, 8, memiss(PAL.ember, 0.5));
    nib.position.y = -0.15;
    stylus.add(shaft, nib);
    stylus.position.set(-0.05, 0.46, -0.02);
    g.add(desk, page, lines, gantry, armH, stylus);
    g.userData.stylus = stylus;
    g.userData.lines = lines.children;
    return g;
  },

  /* Submission head — checkpoint gate, sealed packet, review shield */
  gateway() {
    const g = new THREE.Group();
    const postL = bevelBox(0.16, 1.0, 0.26, mstruct(), 0.03);
    postL.position.set(-0.44, 0.5, 0);
    const postR = postL.clone(); postR.position.x = 0.44;
    const lintel = bevelBox(1.06, 0.16, 0.28, mdark(), 0.03);
    lintel.position.y = 1.06;
    const doorL = box(0.36, 0.78, 0.05, mmetal());
    doorL.position.set(-0.19, 0.47, 0);
    const doorR = doorL.clone(); doorR.position.x = 0.19;
    const lamp = box(0.3, 0.045, 0.05, memiss(PAL.warn, 0.2));  // bright only while holding
    lamp.position.y = 1.17;
    const shield = M(new THREE.PlaneGeometry(0.86, 0.7),
      new THREE.MeshStandardMaterial({ color: PAL.warn, transparent: true, opacity: 0.0, emissive: PAL.warn, emissiveIntensity: 0.25, side: THREE.DoubleSide, depthWrite: false }));
    shield.position.set(0, 0.5, 0.09);
    const packet = box(0.24, 0.16, 0.18, mdark());
    packet.position.set(0, 0.1, 0.42);
    const seal = box(0.1, 0.02, 0.1, memiss(PAL.ember, 0.7));
    seal.position.set(0, 0.19, 0.42);
    const scanner = torus(0.2, 0.015, memiss(PAL.silver, 0.35));
    scanner.position.set(0, 0.62, 0.28);
    g.add(postL, postR, lintel, doorL, doorR, lamp, shield, packet, seal, scanner);
    g.userData.doors = { l: doorL, r: doorR, open: 0, lx: -0.19, rx: 0.19 };
    g.userData.lamp = lamp;
    g.userData.shield = shield;
    return g;
  },

  /* Inbox reader — receiver dish + sorting tray with class chutes */
  antenna() {
    const g = new THREE.Group();
    g.add(bevelBox(0.7, 0.16, 0.5, mstruct(), 0.035));
    const tray = box(0.6, 0.05, 0.34, mdark());
    tray.position.set(0, 0.2, 0.08);
    for (let i = 0; i < 3; i++) {                               // sorting chutes
      const slot = box(0.16, 0.02, 0.3, mstruct(0x15171a));
      slot.position.set(-0.2 + i * 0.2, 0.235, 0.08);
      g.add(slot);
    }
    const mast = cyl(0.03, 0.05, 0.6, 8, mmetal());
    mast.position.set(-0.16, 0.5, -0.14);
    const dish = M(new THREE.SphereGeometry(0.24, 18, 10, 0, Math.PI * 2, 0, Math.PI / 2.6), mmetal(0x7c828a));
    dish.position.set(-0.16, 0.82, -0.14);
    dish.rotation.x = -Math.PI / 1.5;
    const feedTip = M(new THREE.SphereGeometry(0.035, 10, 8), memiss(PAL.silver, 0.8));
    feedTip.position.set(-0.16, 0.95, -0.02);
    g.add(tray, mast, dish, feedTip);
    g.userData.hot = [feedTip.material];
    return g;
  },

  /* Follow-ups — timed return loop with clock and queued packet */
  loop() {
    const g = new THREE.Group();
    g.add(cyl(0.26, 0.34, 0.14, 8, mstruct()));
    const rail = torus(0.34, 0.028, mmetal());
    rail.rotation.x = Math.PI / 2.4; rail.position.y = 0.38;
    const clockF = cyl(0.14, 0.14, 0.03, 20, mstruct(0x15171a));
    clockF.rotation.x = Math.PI / 2; clockF.position.set(0, 0.42, 0.0);
    const hH = box(0.015, 0.07, 0.012, mmetal()); hH.position.set(0, 0.45, 0.02);
    const hM = box(0.012, 0.1, 0.012, memiss(PAL.ember, 0.5)); hM.position.set(0.02, 0.44, 0.02); hM.rotation.z = -0.9;
    const pkt = box(0.09, 0.07, 0.07, mdark());
    pkt.position.set(0.34, 0.38, 0);                            // queued, dormant on the rail
    g.add(rail, clockF, hH, hM, pkt);
    g.userData.railPkt = { o: pkt, rail, t: 0 };
    return g;
  },

  /* Nightly report — ledger stack, stamp arm, archive slot */
  vault() {
    const g = new THREE.Group();
    g.add(bevelBox(0.72, 0.16, 0.56, mstruct(), 0.035));
    const stack = new THREE.Group();
    for (let i = 0; i < 4; i++) {
      const pagep = box(0.4 - i * 0.004, 0.03, 0.3, i === 3 ? mpage() : mdark());
      pagep.position.set(-0.12, 0.16 + i * 0.035, 0.02);
      pagep.rotation.y = (i % 2 ? 1 : -1) * 0.04;
      stack.add(pagep);
    }
    const post = cyl(0.035, 0.05, 0.5, 8, mmetal());
    post.position.set(0.24, 0.38, -0.1);
    const stampArm = new THREE.Group();
    const armB = box(0.3, 0.04, 0.05, mmetal());
    armB.position.x = -0.12;
    const seal = cyl(0.07, 0.09, 0.08, 12, memiss(PAL.ember, 0.35));
    seal.position.set(-0.26, -0.05, 0);
    stampArm.add(armB, seal);
    stampArm.position.set(0.24, 0.6, -0.02);
    const slot = box(0.44, 0.16, 0.06, mstruct(0x15171a));
    slot.position.set(0, 0.22, -0.24);
    g.add(stack, post, stampArm, slot);
    g.userData.stamp = stampArm;
    return g;
  },

  /* Chat agent — waveform console that only moves while processing */
  node() {
    const g = new THREE.Group();
    g.add(cyl(0.28, 0.36, 0.12, 6, mstruct()));
    const bars = new THREE.Group();
    for (let i = 0; i < 5; i++) {
      const b = box(0.07, 0.18 + (i === 2 ? 0.16 : i === 1 || i === 3 ? 0.09 : 0), 0.07,
        memiss(PAL.ember, 0.4, 0x3a3f45));
      b.position.set(-0.2 + i * 0.1, 0.26, 0);
      bars.add(b);
    }
    const slot = box(0.3, 0.02, 0.1, mmetal());
    slot.position.set(0, 0.1, 0.22);
    g.add(bars, slot);
    g.userData.bars = bars.children;
    return g;
  },

  /* Manual queue — quarantine pods under an amber review shield */
  chamber() {
    const g = new THREE.Group();
    g.add(bevelBox(0.8, 0.12, 0.66, mstruct(), 0.03));
    for (let i = 0; i < 3; i++) {
      const pod = cyl(0.11, 0.13, 0.26, 10, mglass(0x2a2418, 0.5));
      pod.position.set(-0.24 + i * 0.24, 0.24, 0.08);
      const lid = cyl(0.12, 0.12, 0.03, 10, memiss(PAL.warn, 0.5));
      lid.position.set(-0.24 + i * 0.24, 0.39, 0.08);
      g.add(pod, lid);
    }
    const shield = torus(0.46, 0.02, memiss(PAL.warn, 0.4), Math.PI);
    shield.position.set(0, 0.3, -0.18);
    g.add(shield);
    return g;
  },

  /* External feeds — antenna terminal */
  pylon() {
    const g = new THREE.Group();
    g.add(bevelBox(0.34, 0.5, 0.3, mstruct(), 0.03));
    const screen = box(0.26, 0.18, 0.02, memiss(PAL.silver, 0.22, 0x22262b));
    screen.position.set(0, 0.42, 0.16);
    const mast = cyl(0.02, 0.03, 0.5, 6, mmetal());
    mast.position.set(0, 0.75, -0.05);
    const cross = box(0.22, 0.02, 0.02, mmetal());
    cross.position.set(0, 0.88, -0.05);
    g.add(screen, mast, cross);
    return g;
  },

  /* Employers / ATS — secured destination terminals behind a boundary */
  terminals() {
    const g = new THREE.Group();
    g.add(bevelBox(1.0, 0.14, 0.6, mstruct(), 0.03));
    for (let i = 0; i < 2; i++) {
      const tw = box(0.26, 0.7 + i * 0.16, 0.26, mdark());
      tw.position.set(-0.22 + i * 0.44, 0.41 + i * 0.08, 0);
      const scr = box(0.2, 0.12, 0.02, memiss(PAL.silver, 0.25, 0x22262b));
      scr.position.set(-0.22 + i * 0.44, 0.62 + i * 0.14, 0.14);
      g.add(tw, scr);
    }
    const arch = torus(0.5, 0.03, mmetal(), Math.PI);
    arch.position.y = 0.55;
    g.add(arch);
    return g;
  },

  /* Human operator — command station (desk + tilted screens), no avatar */
  console() {
    const g = new THREE.Group();
    g.add(bevelBox(0.9, 0.12, 0.55, mstruct(), 0.03));
    const desk = bevelBox(0.8, 0.07, 0.4, mdark(), 0.02);
    desk.position.set(0, 0.3, 0.04);
    for (let i = 0; i < 3; i++) {
      const scr = box(0.24, 0.17, 0.025, memiss(PAL.emberHot, i === 1 ? 0.3 : 0.18, 0x22262b));
      scr.position.set(-0.27 + i * 0.27, 0.52, 0.12);   // faces the room
      scr.rotation.x = 0.25;
      scr.rotation.y = (i - 1) * 0.3;
      g.add(scr);
    }
    const legL = box(0.05, 0.24, 0.4, mmetal(0x565b61));
    legL.position.set(-0.34, 0.17, 0.04);
    const legR = legL.clone(); legR.position.x = 0.34;
    g.add(desk, legL, legR);
    return g;
  },

  /* JobBot Core — elevated faceted intelligence core with segmented rings */
  core() {
    const g = new THREE.Group();
    const pedestal = cyl(0.5, 0.72, 0.5, 8, mstruct());
    pedestal.position.y = 0.25;
    const collar = cyl(0.42, 0.5, 0.1, 8, mmetal());
    collar.position.y = 0.55;
    const heart = M(new THREE.IcosahedronGeometry(0.34, 0), memiss(PAL.ember, 0.35, 0x2a2024));
    heart.position.y = 1.05;
    const cage = M(new THREE.IcosahedronGeometry(0.42, 0),
      new THREE.MeshStandardMaterial({ color: PAL.metal, roughness: 0.3, metalness: 0.9, wireframe: true }));
    cage.position.y = 1.05;
    const rings = new THREE.Group();
    const spine = [];
    for (let i = 0; i < 3; i++) {
      const ring = new THREE.Group();
      for (let s = 0; s < 8; s++) {                             // workload segments
        const seg = torus(0.6 + i * 0.14, 0.022, memiss(PAL.ember, 0.05, 0x3a3f45), Math.PI / 5.2);
        seg.rotation.z = (s / 8) * Math.PI * 2;
        ring.add(seg);
        if (i === 0) spine.push(seg.material);
      }
      ring.rotation.x = Math.PI / 2;
      ring.position.y = 0.78 + i * 0.22;
      ring.rotation.z = i * 0.26;
      rings.add(ring);
    }
    const lampBudget = torus(0.5, 0.018, memiss(PAL.ember, 0.5), Math.PI * 1.2);  // budget arc
    lampBudget.rotation.x = Math.PI / 2; lampBudget.position.y = 0.62;
    const mastS = cyl(0.015, 0.02, 0.22, 6, mmetal());
    mastS.position.y = 1.48;
    const safety = M(new THREE.SphereGeometry(0.05, 12, 8), memiss(PAL.warn, 0.15));
    safety.position.y = 1.6;
    g.add(pedestal, collar, heart, cage, rings, lampBudget, mastS, safety);
    g.userData.spin = { o: cage, axis: "y", sp: 0.004 };        // gentle idle presence
    g.userData.run = [{ o: rings, axis: "y", sp: 0.01 }];
    g.userData.heart = heart;
    g.userData.spine = spine;
    g.userData.budget = lampBudget;
    g.userData.safety = safety;
    return g;
  },

  capsule(color = PAL.metal) {
    return M(new THREE.CapsuleGeometry(0.07, 0.12, 3, 10), mmetal(color));
  },

  bevelBox,
  blobShadow,
  poolLight,

  /* one sealed quarantine pod — a single waiting job */
  pod() {
    const g = new THREE.Group();
    g.add(cyl(0.16, 0.2, 0.1, 10, mstruct()));
    const body = cyl(0.13, 0.15, 0.3, 10, mglass(0x2a2418, 0.5));
    body.position.y = 0.25;
    const lid = cyl(0.14, 0.14, 0.035, 10, memiss(PAL.warn, 0.5));
    lid.position.y = 0.42;
    const latch = box(0.05, 0.03, 0.05, mmetal());
    latch.position.y = 0.45;
    g.add(body, lid, latch);
    g.userData.lid = lid;
    return g;
  },
};

/* ---------------- environmental scenery kit ----------------
   Frames every scene: architecture, floors, rails, silhouettes, light.
   Background pieces are matte, low-contrast, fog-faded — they must never
   compete with interactive equipment. */

export const env = {
  /* curved wall band with recessed emissive slit panels */
  wallArc(r, a1, a2, { h = 2.4, c = 0x111318, slits = 4 } = {}) {
    const g = new THREE.Group();
    const wall = M(new THREE.CylinderGeometry(r, r, h, 48, 1, true, a1, a2 - a1), mmatte(c));
    wall.material.side = THREE.DoubleSide;
    wall.position.y = h / 2;
    g.add(wall);
    const cap = M(new THREE.TorusGeometry(r, 0.035, 8, 64, a2 - a1), mdark());
    cap.rotation.x = Math.PI / 2;
    cap.rotation.z = a1;
    cap.position.y = h;
    g.add(cap);
    for (let i = 0; i < slits; i++) {
      const a = a1 + (a2 - a1) * ((i + 0.5) / slits);
      const s = box(0.05, h * 0.5, 0.4, memiss(PAL.silver, 0.1, 0x2a2d33));
      s.position.set(Math.cos(a) * (r - 0.03), h * 0.52, -Math.sin(a) * (r - 0.03));
      s.rotation.y = a + Math.PI / 2;
      g.add(s);
    }
    return g;
  },

  /* segmented chamber floor: paneled disc, ring channel, radial seams,
     embedded conduit ring that carries a faint ember pulse line */
  floorDisc(r, { seams = 12, channelR = 0, apron = 2.6 } = {}) {
    const g = new THREE.Group();
    const disc = M(new THREE.CircleGeometry(r, 64), mfloor());
    disc.rotation.x = -Math.PI / 2;
    disc.material.roughnessMap.repeat.set(r, r);
    disc.receiveShadow = true;
    g.add(disc);
    if (apron) {                               // dark service apron grounds everything outside
      const ap = M(new THREE.RingGeometry(r, r + apron, 64), mmatte(0x0c0d10));
      ap.rotation.x = -Math.PI / 2; ap.position.y = -0.004;
      ap.receiveShadow = true;
      g.add(ap);
    }
    const rim = M(new THREE.TorusGeometry(r - 0.06, 0.028, 8, 72), mdark());
    rim.rotation.x = Math.PI / 2; rim.position.y = 0.02;
    g.add(rim);
    if (channelR) {
      const ch = M(new THREE.RingGeometry(channelR - 0.09, channelR + 0.09, 64), mmatte(0x0d0e10));
      ch.rotation.x = -Math.PI / 2; ch.position.y = 0.004;
      g.add(ch);
      const glowRing = M(new THREE.TorusGeometry(channelR, 0.012, 6, 72), memiss(PAL.ember, 0.22, 0x3a2d20));
      glowRing.rotation.x = Math.PI / 2; glowRing.position.y = 0.012;
      g.add(glowRing);
    }
    for (let i = 0; i < seams; i++) {
      const a = (i / seams) * Math.PI * 2;
      const seam = box(r * 0.96, 0.004, 0.022, mmatte(0x101114));
      seam.position.set(Math.cos(a) * r * 0.49, 0.009, -Math.sin(a) * r * 0.49);
      seam.rotation.y = a;
      g.add(seam);
    }
    return g;
  },

  /* paneled rectangular room floor with a dark service border */
  floorRect(w, d, { border = 1.8 } = {}) {
    const g = new THREE.Group();
    const f = M(new THREE.PlaneGeometry(w, d), mfloor());
    f.rotation.x = -Math.PI / 2;
    f.material.roughnessMap.repeat.set(w / 2, d / 2);
    f.receiveShadow = true;
    g.add(f);
    const b = M(new THREE.PlaneGeometry(w + border * 2, d + border * 2), mmatte(0x0c0d10));
    b.rotation.x = -Math.PI / 2; b.position.y = -0.004;
    b.receiveShadow = true;
    g.add(b);
    const edge = box(w + 0.05, 0.02, 0.05, mdark()); edge.position.set(0, 0.012, d / 2);
    const edge2 = edge.clone(); edge2.position.z = -d / 2;
    g.add(edge, edge2);
    return g;
  },

  /* embedded floor conduit between two points (dim ember data line) */
  conduit(x1, z1, x2, z2, { lit = 0.08 } = {}) {
    const dx = x2 - x1, dz = z2 - z1, len = Math.hypot(dx, dz);
    const g = new THREE.Group();
    const tray = box(len, 0.015, 0.11, mmatte(0x0d0e10));
    const line = box(len - 0.1, 0.006, 0.022, memiss(PAL.ember, lit, 0x241e18));
    line.position.y = 0.012;
    g.add(tray, line);
    g.position.set((x1 + x2) / 2, 0.012, (z1 + z2) / 2);
    g.rotation.y = -Math.atan2(dz, dx);
    return g;
  },

  /* dim background machinery mass (fog does the rest) */
  silhouette(seed = 0) {
    const g = new THREE.Group();
    const rnd = n => { seed = (seed * 9301 + 49297) % 233280; return (seed / 233280) * n; };
    const base = box(0.9 + rnd(0.8), 0.5 + rnd(0.9), 0.7 + rnd(0.5), mmatte(0x0f1013));
    base.position.y = base.geometry.parameters.height / 2;
    g.add(base);
    const top = box(0.4 + rnd(0.4), 0.3 + rnd(0.6), 0.4, mmatte(0x121317));
    top.position.y = base.geometry.parameters.height + top.geometry.parameters.height / 2;
    top.position.x = rnd(0.4) - 0.2;
    g.add(top);
    if (rnd(1) > 0.4) {
      const stack = cyl(0.07, 0.09, 0.7 + rnd(0.5), 8, mmatte(0x14151a));
      stack.position.set(-0.3, base.geometry.parameters.height + 0.35, 0.1);
      g.add(stack);
    }
    const led = box(0.05, 0.02, 0.02, memiss(PAL.ember, 0.3, 0x2c241c));
    led.position.set(0.2, base.geometry.parameters.height * 0.7, base.geometry.parameters.depth / 2 + 0.01);
    g.add(led);
    return g;
  },

  /* observation rail arc: handrail + posts */
  rail(r, a1, a2) {
    const g = new THREE.Group();
    const top = M(new THREE.TorusGeometry(r, 0.022, 8, 48, a2 - a1), mmetal(0x7c828a));
    top.rotation.x = Math.PI / 2; top.rotation.z = a1; top.position.y = 0.52;
    const mid = M(new THREE.TorusGeometry(r, 0.012, 6, 48, a2 - a1), mdark());
    mid.rotation.x = Math.PI / 2; mid.rotation.z = a1; mid.position.y = 0.3;
    g.add(top, mid);
    const n = Math.max(2, Math.round((a2 - a1) / 0.35));
    for (let i = 0; i <= n; i++) {
      const a = a1 + (a2 - a1) * (i / n);
      const post = cyl(0.02, 0.025, 0.52, 6, mdark());
      post.position.set(Math.cos(a) * r, 0.26, -Math.sin(a) * r);
      g.add(post);
    }
    return g;
  },

  /* directional floor chevrons pointing along +X of the group */
  chevrons(n = 3, { c = PAL.ember, lit = 0.2 } = {}) {
    const g = new THREE.Group();
    for (let i = 0; i < n; i++) {
      const v = M(new THREE.ConeGeometry(0.11, 0.26, 3), memiss(c, lit, 0x2c241c));
      v.rotation.x = -Math.PI / 2;
      v.rotation.z = -Math.PI / 2;
      v.scale.y = 0.5;
      v.position.set(i * 0.4, 0.012, 0);
      g.add(v);
    }
    return g;
  },

  poolLight,
  blobShadow,
};

/* ---------------- scene host ---------------- */

let SCENES = {};
window.__ops3d = window.__ops3d || { scenes: SCENES, three: true };

export class OpsScene {
  constructor(host, opts = {}) {
    this.host = host;
    this.opts = opts;
    this.ok = false;
    this.reduced = reducedMotion();
    // ?q3d=high|low overrides the auto pick (auto: saved pref, or ≤2 cores)
    const q3d = new URLSearchParams(location.search).get("q3d");
    this.lowPower = q3d === "low" ? true : q3d === "high" ? false
      : (lowPowerPref() || (navigator.hardwareConcurrency || 4) <= 2);
    this.nodes = new Map();
    this.paths = new Map();
    this.tasks = new Set();
    this._pool = [];
    this._raf = null;
    this._renderQueued = false;
    this._disposed = false;
    this.selected = null;
    this.presets = opts.presets || {};

    try {
      this.renderer = new THREE.WebGLRenderer({ antialias: !this.lowPower, alpha: false, powerPreference: "low-power" });
    } catch (e) { return; }
    this.renderer.setClearColor(PAL.void, 1);
    this.renderer.toneMapping = THREE.ACESFilmicToneMapping;
    this.renderer.toneMappingExposure = 1.34;
    this.renderer.setPixelRatio(Math.min(devicePixelRatio || 1, this.lowPower ? 1 : 1.75));
    // real key-light shadows on capable devices; the scene is static between
    // events, so autoUpdate stays off and maps refresh only on rendered frames
    this.renderer.shadowMap.enabled = !this.lowPower;
    this.renderer.shadowMap.type = THREE.PCFSoftShadowMap;
    this.renderer.shadowMap.autoUpdate = false;
    this.canvas = this.renderer.domElement;
    this.canvas.setAttribute("role", "img");
    this.canvas.setAttribute("aria-label", opts.ariaLabel || "3D operations scene");
    this.canvas.setAttribute("tabindex", "0");
    this.canvas.style.display = "block";
    this.canvas.style.outline = "none";
    host.classList.add("ops3d-host");
    host.appendChild(this.canvas);
    this.labels = document.createElement("div");
    this.labels.className = "ops3d-labels";
    host.appendChild(this.labels);

    this.scene = new THREE.Scene();
    this.scene.fog = new THREE.Fog(PAL.void, 30, 58);
    // layered light: soft ambient base, warm key (shadowed), neutral fill so
    // shadows keep detail, low ember rim, plus one on-demand selection light
    const hemi = new THREE.HemisphereLight(0xf7f3ec, 0x20242a, 2.0);
    const key = new THREE.DirectionalLight(0xfff0dd, 3.2);
    key.position.set(6, 11, 7);
    if (!this.lowPower) {
      key.castShadow = true;
      key.shadow.mapSize.set(1024, 1024);
      const sb = opts.shadowBounds ?? 11;
      key.shadow.camera.left = -sb; key.shadow.camera.right = sb;
      key.shadow.camera.top = sb; key.shadow.camera.bottom = -sb;
      key.shadow.camera.near = 2; key.shadow.camera.far = 34;
      key.shadow.bias = -0.0006;
      key.shadow.normalBias = 0.025;
      key.target.position.set(0, 0, 0);
      this.scene.add(key.target);
    }
    const fill = new THREE.DirectionalLight(0xdfe6ee, 1.15);
    fill.position.set(-6, 7, 2);
    const rim = new THREE.DirectionalLight(PAL.ember, 0.5);
    rim.position.set(-5, 3, -8);
    this._selLight = new THREE.PointLight(PAL.emberHot, 0, 5.5, 1.8);
    this.scene.add(hemi, key, fill, rim, this._selLight);

    const c = opts.camera || {};
    this.camera = new THREE.PerspectiveCamera(40, 1, 0.1, 90);
    this.rig = {
      target: new THREE.Vector3(...(c.target || [0, 0.4, 0])),
      radius: c.radius ?? 10, theta: c.theta ?? 0, phi: c.phi ?? 0.95,
      minR: c.minR ?? (c.radius ?? 10) * 0.5, maxR: c.maxR ?? (c.radius ?? 10) * 1.55,
      minPhi: 0.3, maxPhi: 1.25, maxTheta: c.maxTheta ?? 1.05,
      panLimit: c.panLimit ?? 2,
    };
    this.rig.home = { radius: this.rig.radius, theta: this.rig.theta, phi: this.rig.phi, target: this.rig.target.clone() };
    this._goal = { radius: this.rig.radius, theta: this.rig.theta, phi: this.rig.phi, target: this.rig.target.clone() };
    this._applyCamera(1);

    this.ray = new THREE.Raycaster();
    this._wireInput();
    this._wireLifecycle();
    this.ok = true;
    SCENES[host.dataset.scene || "scene"] = this;
    this.stats = { ready: true, animating: false, packetsFired: 0,
      mode: this.reduced ? "reduced" : (this.lowPower ? "lowpower" : "full") };
  }

  /* ----- camera ----- */
  _applyCamera(t = 0.12) {
    const r = this.rig, g = this._goal;
    r.radius += (g.radius - r.radius) * t;
    r.theta += (g.theta - r.theta) * t;
    r.phi += (g.phi - r.phi) * t;
    r.target.lerp(g.target, t);
    const sp = new THREE.Vector3(
      r.radius * Math.sin(r.phi) * Math.sin(r.theta),
      r.radius * Math.cos(r.phi),
      r.radius * Math.sin(r.phi) * Math.cos(r.theta));
    this.camera.position.copy(sp.add(r.target));
    this.camera.lookAt(r.target);
  }
  _clampGoal() {
    const g = this._goal, r = this.rig;
    g.radius = Math.min(r.maxR, Math.max(r.minR, g.radius));
    g.phi = Math.min(r.maxPhi, Math.max(r.minPhi, g.phi));
    g.theta = Math.min(r.maxTheta, Math.max(-r.maxTheta, g.theta));
    g.target.x = Math.min(r.panLimit, Math.max(-r.panLimit, g.target.x));
    g.target.z = Math.min(r.panLimit, Math.max(-r.panLimit, g.target.z));
  }
  _cameraSettled() {
    const r = this.rig, g = this._goal;
    return Math.abs(g.radius - r.radius) < 0.002 && Math.abs(g.theta - r.theta) < 0.001 &&
      Math.abs(g.phi - r.phi) < 0.001 && g.target.distanceTo(r.target) < 0.002;
  }
  goTo({ radius, theta, phi, target }) {
    if (radius != null) this._goal.radius = radius;
    if (theta != null) this._goal.theta = theta;
    if (phi != null) this._goal.phi = phi;
    if (target) this._goal.target.set(...target);
    this._clampGoal();
    if (this.reduced) { this._applyCamera(1); this.requestRender(); } else this._kick();
  }
  setPreset(name) {
    if (name === "reset" || !this.presets[name]) return this.resetCamera();
    this.goTo(this.presets[name]);
  }
  resetCamera() {
    const h = this.rig.home;
    this.goTo({ radius: h.radius, theta: h.theta, phi: h.phi, target: [h.target.x, h.target.y, h.target.z] });
  }
  focusOn(id, { radius } = {}) {
    const n = this.nodes.get(id);
    if (!n) return;
    const p = new THREE.Vector3();
    n.group.getWorldPosition(p);
    // keep context: aim between the node and the scene center, never all the way in
    const t = p.clone().multiplyScalar(0.62);
    t.y = p.y * 0.5 + 0.35;
    this._goal.target.copy(t);
    this._goal.radius = Math.max(this.rig.home.radius * 0.55, radius || 0);
    this._clampGoal();
    if (this.reduced) { this._applyCamera(1); this.requestRender(); } else this._kick();
  }

  /* ----- input ----- */
  _wireInput() {
    let drag = null;
    const cv = this.canvas;
    this._onDown = e => { drag = { x: e.clientX, y: e.clientY, pan: e.shiftKey || e.button === 2 }; cv.setPointerCapture(e.pointerId); };
    this._onMove = e => {
      if (!drag) return;
      const dx = (e.clientX - drag.x) / cv.clientWidth, dy = (e.clientY - drag.y) / cv.clientHeight;
      drag.x = e.clientX; drag.y = e.clientY;
      if (drag.pan) {
        const s = this.rig.radius * 0.9;
        this._goal.target.x -= dx * s * Math.cos(this.rig.theta);
        this._goal.target.z += dx * s * Math.sin(this.rig.theta);
        this._goal.target.z -= dy * s * 0.7 * Math.cos(this.rig.theta);
        this._goal.target.x -= dy * s * 0.7 * Math.sin(this.rig.theta);
      } else {
        this._goal.theta -= dx * 2.4;
        this._goal.phi -= dy * 1.8;
      }
      this._clampGoal(); this._kick();
    };
    this._onUp = e => { drag = null; try { cv.releasePointerCapture(e.pointerId); } catch (err) {} };
    this._onWheel = e => { e.preventDefault(); this._goal.radius *= (1 + Math.sign(e.deltaY) * 0.09); this._clampGoal(); this._kick(); };
    this._onKey = e => {
      const step = { ArrowLeft: [0.12, 0], ArrowRight: [-0.12, 0], ArrowUp: [0, -0.08], ArrowDown: [0, 0.08] }[e.key];
      if (step) { e.preventDefault(); this._goal.theta += step[0]; this._goal.phi += step[1]; this._clampGoal(); this._kick(); }
      if (e.key.toLowerCase() === "r") this.resetCamera();
    };
    this._onClick = e => { const hit = this._pick(e); this.select(hit || null, { fromCanvas: true }); };
    this._onHover = e => {
      const hit = this._pick(e);
      if (hit !== this._hover) { this._hover = hit; this._paintStates(); this.requestRender(); }
      cv.style.cursor = hit ? "pointer" : "grab";
    };
    cv.addEventListener("pointerdown", this._onDown);
    cv.addEventListener("pointermove", this._onMove);
    cv.addEventListener("pointerup", this._onUp);
    cv.addEventListener("wheel", this._onWheel, { passive: false });
    cv.addEventListener("keydown", this._onKey);
    cv.addEventListener("click", this._onClick);
    cv.addEventListener("pointermove", this._onHover);
    cv.addEventListener("contextmenu", this._ctx = ev => ev.preventDefault());
  }
  _pick(e) {
    const r = this.canvas.getBoundingClientRect();
    const v = new THREE.Vector2(((e.clientX - r.left) / r.width) * 2 - 1, -((e.clientY - r.top) / r.height) * 2 + 1);
    this.ray.setFromCamera(v, this.camera);
    const hits = this.ray.intersectObjects(this._pickables || [], true);
    for (const h of hits) {
      let o = h.object;
      while (o && !o.userData.nodeId) o = o.parent;
      if (o) return o.userData.nodeId;
    }
    return null;
  }

  /* ----- lifecycle ----- */
  _wireLifecycle() {
    this._ro = new ResizeObserver(() => this._resize());
    this._ro.observe(this.host);
    this._io = new IntersectionObserver(es => {
      this._offscreen = !es[0].isIntersecting;
      if (!this._offscreen) this.requestRender();
    });
    this._io.observe(this.host);
    this._vis = () => { if (!document.hidden) this.requestRender(); };
    document.addEventListener("visibilitychange", this._vis);
    this._resize();
  }
  _resize() {
    const w = this.host.clientWidth, h = this.host.clientHeight || 440;
    if (!w) return;
    this.renderer.setSize(w, h, false);
    this.canvas.style.width = "100%";
    this.canvas.style.height = h + "px";
    this.camera.aspect = w / h;
    this.camera.updateProjectionMatrix();
    this.requestRender();
  }

  /* ----- content ----- */
  addZone({ label, x = 0, z = 0, w = 2, d = 2, y = 0, shape, r1 = 3, r2 = 5, a1 = 0, a2 = Math.PI, labelAt }) {
    let p;
    if (shape === "arc") {                     // curved shelf/apron zones
      p = new THREE.Mesh(new THREE.RingGeometry(r1, r2, 48, 1, a1, a2 - a1),
        new THREE.MeshStandardMaterial({ color: PAL.charcoal, roughness: 0.85, metalness: 0.15, side: THREE.DoubleSide }));
      p.rotation.x = -Math.PI / 2;
      p.position.set(x, y + 0.005, z);
    } else {
      p = build.plate(w, d);
      p.position.set(x, y, z);
    }
    this.scene.add(p);
    if (label) {
      const el = document.createElement("span");
      el.className = "ops3d-zone";
      el.textContent = label;
      this.labels.appendChild(el);
      const lp = labelAt ? new THREE.Vector3(...labelAt)
                         : new THREE.Vector3(x, y + 0.1, z - d / 2 + 0.2);
      (this._zoneLabels = this._zoneLabels || []).push({ el, pos: lp });
    }
    return p;
  }
  addNode({ id, label, sub = "", pos, kind = "node", scale = 1, focusRadius, chrome = "auto" }) {
    const group = (build[kind] ? build[kind]() : build.node());
    let halo = null;
    if (kind !== "core") {                     // status ring seats every machine and carries its state
      halo = torus(0.5, 0.013, new THREE.MeshStandardMaterial({
        color: 0x3a3f45, emissive: PAL.silver, emissiveIntensity: 0.08,
        transparent: true, opacity: 0.6, roughness: 0.6, metalness: 0.3 }));
      halo.rotation.x = Math.PI / 2; halo.position.y = 0.02;
      group.add(halo);
    }
    group.add(blobShadow(kind === "core" ? 1.15 : kind === "pod" ? 0.34 : 0.62));  // soft contact grounding
    group.position.set(...pos);
    group.scale.setScalar(scale);
    group.traverse(o => {
      o.userData.nodeId = id;
      if (o.isMesh && !o.material.transparent) { o.castShadow = true; o.receiveShadow = true; }
    });
    this.scene.add(group);
    (this._pickables = this._pickables || []).push(group);

    const el = document.createElement("button");
    el.type = "button";
    el.className = "ops3d-label";
    el.innerHTML = `<span class="d" aria-hidden="true"></span><b></b><small></small><i class="m"></i>`;
    el.querySelector("b").textContent = label;
    el.querySelector("small").textContent = sub;
    el.addEventListener("click", ev => { ev.stopPropagation(); this.select(this.selected === id ? null : id); });
    el.addEventListener("mouseenter", () => { this._hover = id; this._paintStates(); this.requestRender(); });
    el.addEventListener("mouseleave", () => { if (this._hover === id) { this._hover = null; this._paintStates(); this.requestRender(); } });
    el.addEventListener("focus", () => { this._hover = id; this._paintStates(); this.requestRender(); });
    el.addEventListener("blur", () => { if (this._hover === id) { this._hover = null; this._paintStates(); this.requestRender(); } });
    this.labels.appendChild(el);

    const node = { id, group, el, label, sub, state: "idle", line: "", metric: "",
      labelOffset: 1.0 * scale, focusRadius, chrome, halo, baseY: pos[1], baseScale: scale };
    this.nodes.set(id, node);
    this._syncLabel(node);
    return node;
  }
  setNodeState(id, { state, line, metric } = {}) {
    const n = this.nodes.get(id);
    if (!n) return;
    if (state) n.state = state;
    if (line !== undefined) n.line = line;
    if (metric !== undefined) n.metric = metric;
    this._syncLabel(n);
    this._paintStates();
    this.requestRender();
  }
  _labelTier(n) {
    if (n.chrome === "mini") return "mini";
    if (n.chrome === "full") return "full";
    // auto priority: active, warning, failed, selected, hovered expand;
    // quiet objects wear a compact name tag
    if (this.selected === n.id || this._hover === n.id) return "full";
    if (n.state === "run") return "full";
    // quiet nodes (dense shelves) keep attention in the glyphed dot until hover
    if ((n.state === "fail" || n.state === "blocked") && !n.quiet) return "full";
    return "mini";
  }
  _syncLabel(n) {
    const tier = this._labelTier(n);
    n.el.classList.toggle("mini", tier === "mini");
    n.el.querySelector("small").textContent = n.line || n.sub;
    n.el.querySelector(".m").textContent = n.metric || "";
    n.el.dataset.state = n.state;
    n._dirty = true;
    n.el.setAttribute("aria-pressed", String(this.selected === n.id));
    n.el.setAttribute("aria-label",
      `${n.label}. ${n.line || n.sub || ""}${n.metric ? ". " + n.metric : ""}. State: ${n.state}.`);
  }
  addPath(id, points, { color = PAL.metalDark, arc = 0.6 } = {}) {
    const vs = points.map(p => new THREE.Vector3(...p));
    if (vs.length === 2) {
      const mid = vs[0].clone().lerp(vs[1], 0.5);
      mid.y += arc;
      vs.splice(1, 0, mid);
    }
    const curve = new THREE.CatmullRomCurve3(vs);
    const geo = new THREE.TubeGeometry(curve, 24, 0.02, 6, false);
    const mat = new THREE.MeshBasicMaterial({ color, transparent: true, opacity: 0.22 });
    const mesh = new THREE.Mesh(geo, mat);
    this.scene.add(mesh);
    this.paths.set(id, { curve, mesh, mat, state: "idle" });
    return this.paths.get(id);
  }
  setPathState(id, state) {
    const p = this.paths.get(id);
    if (!p) return;
    p.state = state;
    const style = {
      idle: [PAL.metalDark, 0.2], today: [PAL.emberDeep, 0.5],
      live: [PAL.emberHot, 0.95], in: [PAL.silver, 0.85],
      warn: [PAL.warn, 0.9], error: [PAL.fail, 0.95],
    }[state] || [PAL.metalDark, 0.2];
    p.mat.color.setHex(style[0]);
    p.mat.opacity = style[1];
    this.requestRender();
  }

  /* ----- packets: pooled, directional (capsule + cone head) ----- */
  _makePacket() {
    const g = new THREE.Group();
    const body = M(new THREE.CapsuleGeometry(0.045, 0.09, 3, 8), new THREE.MeshBasicMaterial({ color: PAL.emberHot }));
    body.rotation.z = Math.PI / 2;
    const head = M(new THREE.ConeGeometry(0.05, 0.1, 8), new THREE.MeshBasicMaterial({ color: PAL.emberHot }));
    head.rotation.z = -Math.PI / 2;
    head.position.x = 0.11;
    g.add(body, head);
    g.userData.pkt = true;
    g.userData.mats = [body.material, head.material];
    return g;
  }
  firePacket(pathId, { color = PAL.emberHot, count = 1, dur = 1400, reverse = false } = {}) {
    this.stats.packetsFired = (this.stats.packetsFired || 0) + 1;
    const p = this.paths.get(pathId);
    if (!p || this.reduced) { if (p) this._bumpChip(pathId, count); return; }
    let g = this._pool.pop();
    if (!g) {
      if (this.scene.children.filter(c => c.userData.pkt).length > (this.lowPower ? 10 : 24)) { this._bumpChip(pathId, count); return; }
      g = this._makePacket();
    }
    g.userData.mats.forEach(m => m.color.setHex(color));
    g.visible = true;
    this.scene.add(g);
    let chip = null;
    if (count > 1) {
      chip = document.createElement("span");
      chip.className = "ops3d-chip";
      chip.textContent = "×" + count;
      this.labels.appendChild(chip);
    }
    const t0 = performance.now();
    const task = now => {
      let t = Math.min(1, (now - t0) / dur);
      if (reverse) t = 1 - t;
      const tt = Math.max(0.001, Math.min(0.999, t));
      const pos = p.curve.getPointAt(tt);
      const tan = p.curve.getTangentAt(tt);
      if (reverse) tan.negate();
      g.position.copy(pos);
      g.quaternion.setFromUnitVectors(new THREE.Vector3(1, 0, 0), tan.normalize());
      if (chip) this._place(chip, pos, 14);
      if ((now - t0) >= dur) {
        this.scene.remove(g); g.visible = false; this._pool.push(g);
        if (chip) chip.remove();
        return false;
      }
      return true;
    };
    this.tasks.add(task);
    this._kick();
  }
  _bumpChip(pathId, count) {
    const p = this.paths.get(pathId);
    if (!p) return;
    p.chipCount = (p.chipCount || 0) + count;
    if (!p.chipEl) {
      p.chipEl = document.createElement("span");
      p.chipEl.className = "ops3d-chip";
      this.labels.appendChild(p.chipEl);
    }
    p.chipEl.textContent = "×" + p.chipCount;
    p.chipPos = p.curve.getPointAt(0.5);
    this.requestRender();
  }

  /* ----- one-shot mechanism acts (stylus writing, stamp, gauge, dish) ---- */
  act(id, name, { dur = 1400 } = {}) {
    const n = this.nodes.get(id);
    if (!n || this.reduced) return;
    const u = n.group.userData;
    const t0 = performance.now();
    const task = now => {
      const t = Math.min(1, (now - t0) / dur);
      if (name === "write" && u.stylus && u.lines) {
        u.stylus.position.x = -0.18 + 0.26 * ((t * 4) % 1);
        u.stylus.position.z = -0.1 + 0.055 * Math.floor(t * 4);
        const li = Math.min(3, Math.floor(t * 4));
        for (let i = 0; i <= li; i++) u.lines[i].scale.x = i < li ? 1 : Math.max(0.02, (t * 4) % 1);
      }
      if (name === "stamp" && u.stamp) {
        const k = t < 0.5 ? t * 2 : (1 - t) * 2;
        u.stamp.position.y = 0.6 - 0.28 * k;
      }
      if (name === "gauge" && u.needle) {
        u.needle.rotation.z = -1.1 + Math.sin(t * Math.PI) * 2.2 * (1 - t) + (t > 0.8 ? 0 : 0);
      }
      if (name === "receive" && u.hot) u.hot.forEach(m => { m.emissiveIntensity = 0.9 - 0.6 * t; });
      if (name === "loop" && u.railPkt) {
        const a = t * Math.PI * 2;
        u.railPkt.o.position.set(Math.cos(a) * 0.34, 0.38 + Math.sin(a) * 0.12, Math.sin(a) * 0.2);
      }
      return t < 1;
    };
    this.tasks.add(task);
    this._kick();
  }

  /* ----- selection ----- */
  select(id, { silent } = {}) {
    this.selected = id;
    for (const n of this.nodes.values()) this._syncLabel(n);
    this._paintStates();
    if (id && this.nodes.get(id)) this.focusOn(id, { radius: this.nodes.get(id).focusRadius });
    this.requestRender();
    if (!silent && this.opts.onSelect) this.opts.onSelect(id);
  }
  _paintStates() {
    const HALO = { idle: [0xc9cdd3, 0.08], ok: [0xc9cdd3, 0.14], run: [PAL.ember, 0.4],
                   fail: [PAL.fail, 0.5], blocked: [PAL.warn, 0.42] };
    if (!this.selected) this._selLight.intensity = 0;
    for (const n of this.nodes.values()) {
      const filteredOut = this.dimFilter ? !this.dimFilter(n) : false;
      const dim = filteredOut ? 0.18 : (this.selected && this.selected !== n.id) ? 0.38 : 1;
      const hov = this._hover === n.id || this.selected === n.id;
      if (n.halo) {                            // the ground ring is the status practical
        const [hc, hi] = HALO[n.state] || HALO.idle;
        n.halo.material.emissive.setHex(this.selected === n.id ? PAL.emberHot : hc);
        n.halo.material.emissiveIntensity = this.selected === n.id ? 0.6 : hi;
      }
      if (this.selected === n.id) {            // ember rim practical over the selection
        const v = new THREE.Vector3();
        n.group.getWorldPosition(v);
        this._selLight.position.set(v.x + 0.6, v.y + 1.9, v.z + 0.8);
        this._selLight.intensity = 2.4;
      }
      n.group.traverse(o => {
        if (o.material && o.material.opacity !== undefined) {
          if (o.userData._op0 === undefined) o.userData._op0 = o.material.transparent ? o.material.opacity : 1;
          o.material.transparent = dim < 1 || o.userData._op0 < 1;
          o.material.opacity = o.userData._op0 * dim;
        }
      });
      const wasHov = n.el.classList.contains("hov"), wasSel = n.el.classList.contains("sel");
      n.el.classList.toggle("sel", this.selected === n.id);
      n.el.classList.toggle("hov", !!hov);
      if (wasHov !== !!hov || wasSel !== (this.selected === n.id)) this._syncLabel(n);
      n.el.style.opacity = dim < 1 ? 0.45 : 1;
    }
  }

  /* ----- render loop (on demand) ----- */
  requestRender() {
    if (this._renderQueued || this._disposed) return;
    this._renderQueued = true;
    requestAnimationFrame(t => { this._renderQueued = false; this._frame(t); });
  }
  _kick() { if (!this._raf) this._loop(); else this.requestRender(); }
  _loop() {
    if (this._disposed) return;
    this._raf = requestAnimationFrame(t => {
      this._raf = null;
      const busy = this._frame(t);
      if (busy && !document.hidden && !this._offscreen && !this.reduced && !this.paused) this._loop();
      else this.stats.animating = false;
    });
    this.stats.animating = true;
  }
  _frame(now) {
    this._applyCamera(this.reduced ? 1 : 0.14);
    for (const task of [...this.tasks]) if (!task(now)) this.tasks.delete(task);
    let mech = false;
    if (!this.reduced && !this.paused) {
      for (const n of this.nodes.values()) {
        const u = n.group.userData;
        if (u.run && n.state === "run") { u.run.forEach(r => { r.o.rotation[r.axis] += r.sp; }); mech = true; }
        // the reactor cage turns only while the floor is already working —
        // it rides other animation and never keeps a render loop alive itself
        if (u.spin) u.spin.o.rotation[u.spin.axis] += u.spin.sp;
        if (u.bars) {
          if (n.state === "run") { u.bars.forEach((b, i) => { b.scale.y = 0.7 + 0.5 * Math.abs(Math.sin(now / 180 + i)); }); mech = true; }
          else u.bars.forEach(b => { b.scale.y = 1; });
        }
        if (u.doors) {
          const want = n.state === "run" ? 0.17 : 0;
          if (Math.abs(u.doors.open - want) > 0.004) {
            u.doors.open += (want - u.doors.open) * 0.1;
            u.doors.l.position.x = u.doors.lx - u.doors.open;
            u.doors.r.position.x = u.doors.rx + u.doors.open;
            mech = true;
          }
        }
        if (u.shield) {
          const want = n.state === "blocked" ? 0.3 : 0;
          if (Math.abs(u.shield.material.opacity - want) > 0.01) {
            u.shield.material.opacity += (want - u.shield.material.opacity) * 0.12;
            mech = true;
          }
        }
        if (u.hot && n.state !== "run") u.hot.forEach(m => { if (m.emissiveIntensity > 0.02) { m.emissiveIntensity *= 0.94; mech = true; } });
        if (u.hot && n.state === "run") u.hot.forEach(m => { m.emissiveIntensity = 0.8; });
      }
    }
    // restrained mechanical hover response: a 2% lift, skipped under reduced motion
    if (!this.reduced) {
      for (const n of this.nodes.values()) {
        const t = (this._hover === n.id || this.selected === n.id) ? 1 : 0;
        const want = n.baseScale * (1 + 0.02 * t), wantY = n.baseY + 0.02 * t;
        if (Math.abs(n.group.scale.x - want) > 0.0004 || Math.abs(n.group.position.y - wantY) > 0.0004) {
          n.group.scale.setScalar(n.group.scale.x + (want - n.group.scale.x) * 0.25);
          n.group.position.y += (wantY - n.group.position.y) * 0.25;
          mech = true;
        }
      }
    }
    this._projectLabels();
    if (this.renderer.shadowMap.enabled) this.renderer.shadowMap.needsUpdate = true;
    this.renderer.render(this.scene, this.camera);
    const info = this.renderer.info.render;
    this.stats.draws = info.calls; this.stats.tris = info.triangles;
    return this.tasks.size > 0 || !this._cameraSettled() || mech;
  }
  _place(el, v, dy = 0) {
    const p = v.clone().project(this.camera);
    const r = this.canvas.getBoundingClientRect();
    const anchor = el.dataset && el.dataset.below ? "translate(-50%, 10px)" : "translate(-50%,-100%)";
    el.style.transform = `${anchor} translate(${(p.x * 0.5 + 0.5) * r.width}px, ${(-p.y * 0.5 + 0.5) * r.height - dy}px)`;
    el.style.display = p.z < 1 ? "" : "none";
  }
  _projectLabels() {
    const v = new THREE.Vector3();
    const r = this.canvas.getBoundingClientRect();
    const items = [];
    for (const n of this.nodes.values()) {
      n.group.getWorldPosition(v);
      v.y += n.labelOffset;
      const p = v.clone().project(this.camera);
      if (p.z >= 1) { n.el.style.display = "none"; continue; }
      n.el.style.display = "";
      if (!n._w || n._dirty) { n._w = n.el.offsetWidth; n._h = n.el.offsetHeight; n._dirty = false; }
      const below = !!n.el.dataset.below;
      let x = (p.x * 0.5 + 0.5) * r.width;
      let y = (-p.y * 0.5 + 0.5) * r.height;
      x = Math.max(n._w / 2 + 4, Math.min(r.width - n._w / 2 - 4, x));
      const top = below ? y + 10 : y - n._h;
      items.push({ n, x, top: Math.max(4, Math.min(r.height - n._h - 4, top)), below });
    }
    const hostH = this.host.clientHeight || 440;
    const clampTop = it => { it.top = Math.max(4, Math.min(hostH - it.n._h - 4, it.top)); };
    for (let pass = 0; pass < 4; pass++) {
      let moved = false;
      for (let i = 0; i < items.length; i++) {
        for (let j = i + 1; j < items.length; j++) {
          const a = items[i], b = items[j];
          if (Math.abs(a.x - b.x) >= (a.n._w + b.n._w) / 2 + 6) continue;
          const [up, lo] = a.top <= b.top ? [a, b] : [b, a];
          const oy = up.top + up.n._h + 4 - lo.top;
          if (oy <= 0) continue;
          moved = true;
          // monotonic: raise an above-anchored upper, otherwise cascade the
          // lower one down — mixed anchors must never trade places per pass;
          // whatever the clamp eats, the other label absorbs
          if (!up.below) {
            up.top -= oy;
            clampTop(up);
            const rem = up.top + up.n._h + 4 - lo.top;
            if (rem > 0) { lo.top += rem; lo.below = true; }  // ceiling-stuck: lo cascades down from here on
          } else lo.top += oy;
          clampTop(lo);
        }
      }
      if (!moved) break;
    }
    for (const it of items)
      it.n.el.style.transform = `translate(${Math.round(it.x - it.n._w / 2)}px, ${Math.round(it.top)}px)`;
    for (const z of this._zoneLabels || []) {
      this._place(z.el, z.pos);
      if (!z._w) { z._w = z.el.offsetWidth; z._h = z.el.offsetHeight; }
      // a floor caption yields to any data label that lands on it
      const zp = z.pos.clone().project(this.camera);
      const zx = (zp.x * 0.5 + 0.5) * r.width, zy = (-zp.y * 0.5 + 0.5) * r.height;
      let covered = false;
      for (const it of items)
        if (Math.abs(it.x - zx) < (it.n._w + z._w) / 2 + 4 &&
            zy > it.top - 2 && zy - z._h < it.top + it.n._h + 2) { covered = true; break; }
      z.el.style.opacity = covered ? "0.12" : "";
    }
    for (const p of this.paths.values()) if (p.chipEl && p.chipPos) this._place(p.chipEl, p.chipPos, 8);
  }

  dispose() {
    this._disposed = true;
    cancelAnimationFrame(this._raf);
    this.tasks.clear();
    const cv = this.canvas;
    cv.removeEventListener("pointerdown", this._onDown);
    cv.removeEventListener("pointermove", this._onMove);
    cv.removeEventListener("pointermove", this._onHover);
    cv.removeEventListener("pointerup", this._onUp);
    cv.removeEventListener("wheel", this._onWheel);
    cv.removeEventListener("keydown", this._onKey);
    cv.removeEventListener("click", this._onClick);
    cv.removeEventListener("contextmenu", this._ctx);
    document.removeEventListener("visibilitychange", this._vis);
    this._ro.disconnect(); this._io.disconnect();
    this.scene.traverse(o => {
      if (o.geometry) o.geometry.dispose();
      if (o.material) (Array.isArray(o.material) ? o.material : [o.material]).forEach(m => m.dispose());
    });
    this.renderer.dispose();
    this.labels.remove();
    cv.remove();
    delete SCENES[this.host.dataset.scene || "scene"];
    this.stats = { ready: false, animating: false };
  }
}
