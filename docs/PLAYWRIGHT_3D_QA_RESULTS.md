# Playwright 3D QA results — Cyber Operations branch (2026-08-31)

Tooling: venv Playwright (see docs/3D_CAPABILITY_RESEARCH.md re playwright-cli).
Target: isolated :8091 (worktree code, snapshot DB + snapshot answer file).
All browser rendering under `--use-gl=swiftshader` — CPU-only WebGL, the
worst-case floor; a real GPU (the operator's PC) is strictly faster.
Artifacts (screenshots, findings JSON, perf JSON, the three suite scripts)
live in the session scratchpad `ops3d/` — not committed by policy.

## Capture matrix

8 routes × 7 viewports (1920×1080, 1600×900, 1440×900, 1366×768, 1280×800,
768×1024, 390×844), console/pageerror/requestfailed listeners + horizontal
overflow probe on every load; Knowledge Vault masked by default in-app.

| Round | Code state | Result |
| :--- | :--- | :--- |
| baseline (pre-3D) | `212addb` | 56 shots, findings CLEAN |
| final | branch head | 56 shots, findings CLEAN |

## Existing-behavior regression suite (session-13 acceptance, adapted to the mode switcher)

**All checks pass** — routes + active rail state, skip links, zero banner
stacks / zero "queue: clear", rail collapse keyboard + persistence, drawer
dialog focus contract (focus-in, 30-Tab cycle, Esc, focus return), intro
once-ever from a fresh browser profile, needs-you persistence after read,
history tab, schematic core + pod interactions, list view, deep links
(#app-N pin, ?class=, ?outcome=&date=, #review), Knowledge Vault masking +
reveal, queue letter button, ~200% zoom, reduced-motion 2D, mobile drawer.

## 3D acceptance suite — 35 checks, ALL PASS

Scene ready on all eight pages · canvas `role=img` + living label · label
twins take keyboard focus · Enter selects, opens inspection, sets
`aria-pressed` · Esc exits focus · zoom/orbit clamped at the rig limits ·
Reset restores home pose · resize preserves camera aspect · **live truth:**
10 s idle watch fires zero packets, then one real `activity_log` row
(inserted into the snapshot through the audit schema) produced exactly one
packet · LIVE badge ↔ REPLAY · HISTORICAL badge, scrubber engages, pause
halts the sequence, back-to-live restores · pause control · List mode = real
8-row table · low-power honored (persisted pref) · reduced-motion = static
scene, `animating:false` · **forced WebGL failure** (init script nulls
`getContext`) → schematic + note, zero page errors · mobile 390 = no canvas,
no overflow.

## Bugs found by this QA and fixed on the branch

1. **SSE replay duplication** — connections self-terminate (~55 s) and
   EventSource reconnects with the original query `since_id`, re-delivering
   events (caught by the live-truth check: one row → two packets). Fixed:
   honor the `Last-Event-ID` reconnect header server-side + client dedupe.
2. **Waitress thread starvation under navigation** — each page holds one SSE
   stream; slow disconnect detection let a few stale streams exhaust the
   pool (route loads spiked to 2–6.7 s in the perf run). Fixed: 1.2 s
   heartbeat (fast dead-client detection), DB poll every other beat, serve
   threads 8→16. Loads returned to 69–177 ms.
3. **`.tiles/.tile` CSS regression** (pre-existing, shipped in session 13,
   live on master now): the v2 stylesheet dropped the tile rules while
   Applications/Submissions still use them — summary tiles render unstyled.
   Restored here; reaches master with this merge.

## Performance (measured, software-rendering floor)

| Route | load | scene ready | draws | tris | heap |
| :--- | ---: | ---: | ---: | ---: | ---: |
| Mission Control | 74 ms | 247 ms | 59 | 6.5 k | 10 MB |
| Intervention Bay | 69 ms | 213 ms | 39 | 1.5 k | 10 MB |
| Signal Intelligence | 95 ms | 194 ms | 49 | 3.6 k | 10 MB |
| Opportunity Pipeline | 93 ms | 224 ms | 43 | 2.0 k | 10 MB |
| Secure Egress | 177 ms | 183 ms | 34 | 1.5 k | 10 MB |
| Knowledge Vault | 78 ms | 140 ms | 53 | 7.8 k | 10 MB |
| Network Operations | 150 ms | 276 ms | 93 | 10.9 k | 10 MB |
| Operator Console | 1253 ms* | 106 ms | 2 | 32 | 10 MB |

Replay burst (speed 5×, Agents): 29 fps avg, p95 frame 44 ms **on CPU**.
Heap flat at 10-11 MB across six scene↔list mode toggles (no leak).
All scenes idle at zero RAF (on-demand rendering). Baseline (2D-only) loads
were the same order (~70–100 ms), so the 3D layer adds no route-load cost —
it initializes after paint, ≤ ~280 ms.
\* one-off tail measurement straddling an SSE reconnect; repeat loads ~80 ms.

## Audits

Vercel web-interface-guidelines (fetched checklist, re-applied): the
session-13 fixes stand; new surfaces conform (icon buttons labeled, focus
visible, Esc paths, reduced motion, touch-action, no hover-only info,
canvas as enhancement with DOM equivalents). Anti-generic critique (fetched
frontend-design principles standing in for the uninstalled Taste): no
starfields/neon grids/fake code/force graphs; every mark carries a real
value; one signature element (the operations table) with disciplined
surroundings; idle scenes are calm.
