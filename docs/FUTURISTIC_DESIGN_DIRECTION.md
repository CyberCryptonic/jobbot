# JobBot design direction — "Opportunity Intelligence System" (session 13)

## Thesis

JobBot is a private instrument built by one operator to run an autonomous job
search. The design language is **instrumentation, not decoration**: warm
graphite metal, smoked glass, titanium hairlines, and a single rationed vein of
ember light that appears only where the system is alive or wants the operator's
hand. Every mark on screen — ring, tick, rail, counter — encodes a real value
from the tracker. The subject matter (SOC operations: telemetry, audit logs,
review gates, budgets) supplies the vernacular; nothing is borrowed from any
film property.

Emotional benchmark (not a visual source): a precision tool a private engineer
would build for themselves. Original geometry, original instrument design,
original naming. **No Marvel/Iron Man/JARVIS/arc-reactor/HUD imitation of any
kind.**

Named AI-default clusters deliberately avoided (per Anthropic frontend-design
guidance, fetched at source): cream+serif+terracotta; near-black+acid-accent;
broadsheet-hairline layouts. This system escapes the second cluster by warm
(not blue-black) surfaces, an ember accent used as *light on metal* (glow,
arcs, rails) rather than neon text, meaningful instrumentation, and asymmetric
composition — not by adding more saturation.

## Token system (computed, not eyeballed — `contrast.py`, all pass WCAG)

Surfaces (warm graphite, never pure black):
- `--void #0B0B0A` page plane · `--surface-1 #141312` shell/rails
- `--surface-2 #1a1a19` panels & **chart surface (unchanged — the validated
  dataviz surface)** · `--surface-3 #232120` raised · `--glass rgba(20,19,18,.72)`
  + `backdrop-blur` for rails/drawer (solid fallback)

Hairlines ("titanium"): `--line rgba(235,225,210,.09)` · `--line-2 rgba(235,225,210,.17)`

Ink (warm white): `--ink #F2EFE9` (15.2:1 on panels) · `--ink-2 #C8C3B8` (9.9:1)
· `--muted #8C8779` (4.9:1; rule: never essential copy on `--surface-3`)

Energy (ember/copper — the brand vein): `--em-1 #FFB27A` hot text ·
`--em-2 #F08A4B` primary accent (7.0:1) · `--em-3 #D96F2E` deep (5.2:1) ·
`--em-glow rgba(240,138,75,.16)`. Used for: active nav, focus halo, primary
actions, core-instrument arcs, live-flow edges, needs-you rails. Never used to
mean a status.

Cool data accent (small, semantic only): `--data #5B9BE8` (6.1:1) — links,
selected data, run-in-flight. Electric blue is demoted from brand to data.

Status (unchanged validated set; icon/label ALWAYS present): ok `#0ca30c`,
warn `#fab219`, serious `#ec835a`, crit `#d03b3b`. Chart series palette
`--s1..--s5` unchanged — it passed the dataviz validator on `#1a1a19` and
charts remain the one legitimately cool region ("small cool data accent").

## Typography

Inter (UI) + JetBrains Mono (data), self-hosted, unchanged families. Scale up:
base **15px/1.55**; H1 26/650 tracking −0.02em; section labels 10.5px
micro-caps mono +1.4px tracking; hero numerals JBMono 34–44 tabular; table
12.5–13. Numbers are always tabular. No new/remote faces.

## Material & depth

Panels: 1px warm hairline, 12px radius, faint top light (inset gradient), one
elevation shadow tier for raised elements (drawer, focus). Smoked glass only on
the two rails and the drawer. Texture: the page keeps a 2.8% warm dot-grid —
one texture, everywhere, never inside charts.

## Composition & hierarchy

- Fluid width: `main` pads `clamp(20px, 3.2vw, 48px)`, content cap 1840px
  centered — the 1240px column is gone; 1280→1920+ each get deliberate layouts.
- Asymmetry: pages lead with **one dominant operational story** (hero band or
  instrument) and support it with a quiet stat strip — never a wall of
  equal tiles. 8/4 and 7/5 grid splits are the norm.
- Structure encodes meaning: every ring/arc/rail/counter is captioned with the
  real value it draws (target, cap, queue limit). No decorative grids, hexes,
  circuit traces, or invented numbers, ever.
- Signature element: the **Core instrument** on Agent Mesh (three captioned
  arcs: daily auto-apply vs target · month spend vs cap · queue pressure vs
  cap, with the system state word at center). Everything around it stays
  disciplined.

## Motion rules

- One orchestrated load moment: a ≤360ms staggered rise/fade (`transform` +
  `opacity` only) across a page's top-level regions. Nothing else animates by
  default.
- Live-only animation: flow edges and pulse dots animate **only while a run is
  actually in flight**; finished-today is a static warm tint; idle is quiet.
- Drawer/panel transitions 200ms transform; hovers are 120ms border/lift.
- `prefers-reduced-motion`: all of the above collapse to instant static states
  (a dedicated media block, verified in the browser).
- No Three.js/WebGL/GSAP/canvas engines/particles/sound. None is needed; none
  is added.

## Anti-patterns (checked against, page by page)

Equal-card walls · repeated global banners · icon-only mystery nav · neon-on-
black text · dual axes or decorated charts · fake telemetry or invented agent
state · animation on idle systems · pure black/white · centered narrow column
on a 1920 display · unlabeled status color · PII visible by default.

## Engineering boundary

Flask + vanilla JS + Chart.js preserved. No framework, no Tailwind, no CDN, no
new runtime service, no remote font. All existing routes, APIs and security
behavior (escaping of untrusted posting/email text, chat proposal gates)
unchanged. New backend surface is limited to notification read-state
(`notif_seen` table + one POST) and richer `/api/agents` fields — all real data.
