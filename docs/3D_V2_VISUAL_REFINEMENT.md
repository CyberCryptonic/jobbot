# 3D v2 — Visual Refinement (session 15)

Extends the session-14 documents; where this file disagrees with them, this
file wins. Branch `worktree-design+3d-visual-refinement-v2`, cut from frozen
`efaaa4e`. Everything here is implemented and verified on the :8091 preview.

## Art direction v2

Obsidian/graphite surfaces, brushed-metal details, lighter charcoal machine
bodies (`PAL.structural #262a30`, `charcoal #2b2e34`), ACES tone mapping at
exposure 1.28, three-point light (warm key 3.1, cool fill 1.0, crimson rim),
fog 30–58. **Crimson is the single energy accent**:

| token | hex | role |
|---|---|---|
| `--cr-1` | `#EC5F7C` | text-safe accent (5.4:1 on panels), LIVE, links, focus |
| `--cr-2` | `#C22A52` | UI fills, borders, primary buttons |
| `--cr-3` | `#8E1E3C` | deep/decorative (rejection records, gradients) |
| `--warn` | `#fab219` | **waiting on a human** — holds, pods, safety lamp |
| `--ok`   | `#0ca30c` | **wins only** (interviews, offers, healthy) |
| `--fail` | `#E23B2E` | **system failures only**, always with a glyph |
| `--silver` | `#C9CDD3` | inbound traffic, calibration, prepared work |
| ember    | `#F08A4B` | supporting orange: budget arc, score fill, count chips |

No blue, no cyan, anywhere. Chart series remain the validated dataviz set.

## Semantic machine library (`build.*` in ops3d.js)

radar (lens on articulated arm; glow lit only while scanning) · rings
(gauge: dial, silver calibration arc, ember score fill, crimson needle) ·
forge (drafting table; stylus writes real lines via `act("write")`) ·
gateway (checkpoint: doors open on real sends, amber lamp bright only while
holding, review shield fades in when blocked, scanner ring) · antenna
(receiver dish + three sorting chutes; feed tip glows on receipt) · loop
(clock + return rail; dormant packet orbits once per real follow-up) ·
vault (ledger stack + stamp arm that falls on report_generated) · node
(five waveform bars, move only while the chat agent works) · chamber /
pod (sealed amber-lidded quarantine units — `pod` is the single-job form) ·
pylon (feed terminal) · terminals (employer towers + arch, rotated to face
their gateway) · console (operator desk + three crimson screens — never an
avatar) · core (elevated reactor: crimson heart brightness = autonomy,
budget arc = real month spend, 8-segment spine = queue pressure, masthead
safety lamp = amber on hold / red on pause; wire cage turns only while the
floor is already animating so idle stays on-demand).

Every node gets a faint silver station halo; walls carry a lit top edge.

## Camera & presets

`goTo({radius,theta,phi,target})`, damped. Presets from `opts.presets` via
`setPreset(name)`: agents ships `workflow`, `review`, computed `attention`
(centroid of failed/held nodes, recomputed each setData; falls back to home
when nothing needs eyes), and `reset`. Focus keeps context (target pulled
62% toward the node, radius floored at 55% of home).

## Label system v2

Auto tier: quiet = mini tag (name + 6px dot); run/fail/blocked, hover,
focus, or selection = full panel (sub + line + metric, widths 215/240px).
`node.quiet` keeps dense shelves (queue pods) at mini even when blocked —
attention stays in the glyphed dot. States are never color-alone: full-tier
dots carry ▸ ✓ ✕ !, mini attention dots go square. The de-overlap solver is
monotonic (above-anchored upper rises, otherwise the lower cascades down; a
ceiling-stuck pair converts to downward cascade) — the v1 solver oscillated
on mixed anchors. Zone captions yield (fade to 12%) under any data label.
Verified: zero clipped, zero overlapping at 1920×1080, 1600×900, 1440×900,
1366×768, 1280×720, 1024×768 and 200% zoom on all six scene pages.

## Scenes

- **Overview — round command dais** (primary homepage visual, hero slimmed,
  stats band moved below): stations arc around a mini reactor; found/applied
  pillars are real counts; core heart/safety mirror pipeline state.
- **Agents — the factory floor** (canonical): wide zone plan, elevated core
  at center, forge offset from the core's sightline, boundary walls with
  gate gaps, extra source masts. Event wiring is mechanism-true
  (letter → stylus + packet; score → gauge swing; send → doors; email →
  dish + silver packet; report → stamp; follow-up → rail orbit; errors →
  red path + glyph). Gateway lamp reads the real awaiting_review flag.
- **Queue — quarantine shelf**: one sealed pod per waiting job on a curved
  arc shelf (engine `addZone({shape:"arc"})`), number tags (company on
  hover/selection and always in the cards), selected pod moves to the
  inspection platform; `you` is the operator console.
- **Egress**: ready bay silver (prepared ≠ success), handoff amber, launch
  ramp lit at rest, terminals face the gateway.
- **Inbox**: rejections are deep-crimson records (red stays reserved for
  system failures); wins are green.
- Pipeline / vault / copilot carry over with v2 materials.

## First-use tour

`startAgentsTour` (scenes3d.js): five steps riding the real presets;
role=dialog, keyboard-complete (→ ← Enter Esc), Skip on every step; posts
`tour-v1` to `/api/notifs/seen` (server-persisted, once ever); never
auto-runs under reduced motion; ✦ Tour replays on demand. No backend
changes — the existing seen-keys API carries it.

## Loading

Every scene host ships static placeholder markup (`.scene-loading`,
"Initializing spatial view…", spinner that parks under reduced motion) —
visible from first paint, removed when the scene mounts, host folds away
when 3D never happens. Fixed host heights: no layout shift, no fake percent.

## Phone IA (≤900px)

Queue: 5 full cards + "Load 5 more — N still waiting". Chat: day
separators, same-speaker grouping (5-min window), conversation search with
match count, jump-to-latest (appears when scrolled up; scroll is never
yanked while reading), sticky crimson-tinted composer. Agents: timeline
collapses to per-day `<details>` (today open; failures counted in the
summary); the 2D schematic is the touch surface. Answers + egress tables
become stacked cards with their own captions. 44px targets on chips, segs,
pods. Empty 3D shells fold away (`.panel:has(> .ops3d-host)`).

## Performance

Software floor (SwiftShader, no GPU here): routes load 51–116 ms, scenes
ready 150–322 ms, heaviest scene 190 draws / 51k tris, camera flight ~13
fps — and idle costs nothing (on-demand rendering verified: `animating:
false` after settle; hidden tabs pause). Low-power: DPR 1, no AA. Reduced
motion: single static frame. Hardware numbers are measured on the user's
machine only: `__ops3d.scenes.agents.stats` + Chrome's FPS meter.

## Verification (all green, 2026-09-01)

`pytest tests/` 165 · validate_v2 (labels 7 sizes + zoom, zone yield, dead
links, metric truth) · ported 3D suite (live truth: idle 0 packets, 1 row =
1 packet) · ported 2D suite 67 · v2-specific 27 (presets, loading, tour ×7,
phone IA ×13). Suites live in the session scratchpad (`v2/*.py`); they run
against the isolated :8091 preview with snapshot data and QA-labeled probe
rows only.

## Gotcha for future sessions

Run `pytest tests/` — never bare `pytest` from the repo root: the root
`test_smtp.py` connection script sends a real email at import time.
