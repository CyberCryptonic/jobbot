# 3D Cyber Operations design system (session 14)

Extends docs/FUTURISTIC_DESIGN_DIRECTION.md — every 2D token, type rule, and
motion rule stands. This doc adds the third dimension.

## The three depth levels (every page)

1. **Environment layer** — one WebGL scene per page (single canvas), inside a
   `.panel` scene host with the standard panel chrome. It explains structure,
   state, and movement. It never holds editable text, never replaces a table.
2. **Interface layer** — the session-13 HTML shell: rails, filters, chips,
   labels, inspection panels. HTML labels float over the canvas (projected
   each frame), so text is always crisp, selectable, and screen-readable.
3. **Evidence layer** — the existing tables/cards/forms/screenshot strips,
   below or beside the scene, always present (scene view toggles never remove
   them, they collapse them behind an explicit mode switch with state kept).

## Materials (shared library, procedural only)

obsidian floor `#0B0B0A` (rough, near-black) · graphite structure `#1A1918` ·
smoked glass panels (transmission-free: color `#141312`, opacity .55,
depthWrite off) · titanium edges `#8C8779` metallic hairlines · warm-white
label ink (HTML, not textures) · **ember** `#F08A4B` energy/emissive for
active/outbound · **ice** `#7FB4E8` inbound telemetry only · status green
`#0ca30c` / amber `#fab219` / red `#d03b3b` / gray `#8C8779`. Fog: subtle
(`#0B0B0A`, far-only) for depth, never obscuring labels. Lighting: one warm
hemisphere + one key directional + one faint ember rim; no shadows (cost).

Semantics are fixed: ember = active processing/outbound, ice = inbound,
green = healthy/complete, amber = needs a human, red = failed/blocked,
gray = idle/historical. **Never color alone**: every state pairs with the
node's label text, shape state (open gate/closed gate, raised/lowered), or
motion state — and the DOM twin carries the words.

## Geometry vocabulary (hardware-inspired, all procedural)

Zone plates (beveled slabs with titanium edge strips) · trust boundaries (low
smoked-glass walls with gate gaps) · radar/scan dish (Discovery) · stacked
analysis rings (Scoring) · layered document forge (Letter writer) · armored
gateway arch with doors (Submission head / egress) · antenna array (Inbox) ·
response loop torus (Follow-ups) · hardened vault block (Report) · operator
node (Chat) · amber quarantine chamber (Queue) · capsule (job/application) ·
packet (pooled small octahedron) · the **JobBot Core**: an original stacked
assembly — three offset-rotated graphite slabs, a slow status ring, and a
vertical ember spine whose lit segments equal real workload. Explicitly not a
disc, not a circle-in-a-housing, no radial glow prop.

## Motion

Idle scene: completely calm (on-demand rendering; zero RAF). Motion happens
only for: a real event packet traversing a path, a camera move (user or focus
tween, damped), a state transition (gate opens because the state changed), or
hover/selection emphasis. Failed state: the node and its path hold a steady
red edge — no flashing. Reduced motion: scenes render one static frame with
all states shown positionally; packets are replaced by count badges on paths;
camera tweens become jumps.

## Prohibitions carried from the directive

No starfields, neon grids, fake code, hexagon filler, invented packets or
telemetry, idle pulsing, first-person camera, sound, humanoid figures,
full-screen post-processing, CDN assets, or any Marvel/film likeness.
