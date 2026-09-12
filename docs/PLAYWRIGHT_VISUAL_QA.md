# Playwright visual & interaction QA — redesign branch (2026-08-31)

Tooling: Playwright (Python, the repo's own venv — the same engine driving the
17 pre-existing browser tests; the standalone `playwright-cli` binary is not
installed, see docs/CAPABILITY_RESEARCH.md). All runs target the isolated
instance on :8091 — worktree code, snapshot database and snapshot answer file;
the live :8090/master instance was never exercised or modified.

## Manifest

Three full captures, each **8 routes × 4 viewports = 32 screenshots**
(1920×1080, 1440×900, 1280×800, 390×844; full-page at 1920 and 390), stored as
session artifacts under the session scratchpad (`redesign/baseline`,
`redesign/slice1`, `redesign/final` + `redesign/slice2` interaction shots) —
deliberately **not committed** (disposable browser artifacts, and several
contain operator context). Findings JSON accompanies each set.

| Capture | Code state | Console errors | Failed requests | Horizontal overflow |
| :--- | :--- | :--- | :--- | :--- |
| `baseline` (pre-change) | master `7d74058` | 0 | 0 | 0 px on all 32 |
| `slice1` (shell+mesh slice) | mid-branch | 0 | 0 | 0 px on all 32 |
| `final` | branch `87a1748` | 0 | 0 | 0 px on all 32 |

PII: the Knowledge Core now masks identity, sensitive rows, and the references
block **by default in the app itself**, so every final screenshot is safe by
construction; the baseline capture masked those regions with injected CSS
before shooting.

## Interactive acceptance suite (74 checks — ALL PASS)

Navigation: every route loads with exactly one active rail item and correct
`href`; skip link present everywhere; **zero banner stacks and zero
"queue: clear" text on any route**.

Rail: collapses and re-expands via keyboard (Enter on the toggle); the
collapsed preference survives reload (device-level localStorage — the one
deliberate localStorage use); mobile (<860px) turns the rail into a drawer:
menu button visible, focus moves into the rail, Esc closes and restores.

Notification drawer: bell exposes a meaningful accessible name with counts;
opens as `role="dialog"` with focus moved in; 30 consecutive Tabs stay inside
the dialog; Esc closes and focus returns to the bell. Tabs switch Needs
you / System / History. **Mark read persists on the server** (verified from a
fresh browser profile — no cookies/localStorage carried); the intro notice
appears exactly once ever; a needs-you item stays listed after being read
(class `seen`, badge calmed); History renders the activity-log-derived trail.

Agent Mesh: Core instrument renders the real state word (REVIEW HOLD during
the run); pods carry full aria-labels; selecting a pod opens the inspection
panel with its story and pre-filters the decision log; back-to-mesh clears it;
List view is a real 8-row table; the attention filter dims quiet pods.

Deep links: `/applications#app-N` pins the record; `/inbox?class=action_needed`
preselects the chip; `/agent?outcome=fail&date=…` prefills the log filters;
`/submissions#review` shows and flashes the ramp banner.

Knowledge Core masking: identity masked (≥4 masked values) until the explicit
Reveal (aria-pressed); sensitive bank rows masked with per-row Reveal
(verified to unmask exactly one value); references prose blurred behind its
own reveal.

Action Bay: cards render the evidence/decision split; at least one card
serves the letter PDF link (the real download was click-verified in the
session-12 pass and the endpoint is unchanged).

Zoom ≈200%: 960×540 viewport (half of 1920) shows no horizontal overflow on
Mission Control or Agent Mesh. Reduced motion (`prefers-reduced-motion:
reduce` context): content fully visible with no rise animation, and live mesh
edges have `animation-name: none`.

No pageerror and no failed request was recorded across the entire suite.

## Color & contrast verification (computed, never eyeballed)

- Chart palette: unchanged from the session-12 validated set — categorical
  5-slot, 2-series pair, and 3-slot all-pairs runs of the dataviz
  `validate_palette.js` all PASS on the `#1a1a19` chart surface.
- New UI tokens: WCAG ratios computed by script (`contrast.py`) on all four
  surfaces — body inks 9.9–15.2:1, muted 4.9:1 on panels (rule recorded:
  muted never carries essential copy on `--surface-3`), ember accents
  5.2–7.0:1, data accent 6.1:1, status colors ≥3.3:1 and never label-free.

## Known, deliberate limitations

- Filter state syncs **from** the URL (deep links) but not all filter changes
  write **back** to the URL — kept from the previous design; candidate
  follow-up.
- Tables are server-capped (200–500 rows) instead of virtualized — right-sized
  for a single-operator LAN tool.
- Time/number formats are fixed en-US + AM/PM by operator rule, not
  `Intl`-negotiated.
- The Vercel Web Interface Guidelines checklist (fetched from
  vercel-labs/web-interface-guidelines at source) was applied as the final
  audit; fixes landed for aria-labels on filter controls, anchor
  `scroll-margin-top`, `text-wrap: balance`, search `autocomplete="off"`,
  clamped long chip content, explicit select colors, `touch-action`,
  tap-highlight, and `overscroll-behavior` in the drawer.

## How to re-verify

Start an isolated instance (worktree code + a `VACUUM INTO` snapshot DB +
copied answer file, waitress on :8091), then run the capture (8 routes × 4
viewports, console/pageerror/requestfailed listeners + `scrollWidth`
overflow probe) and the acceptance suite (this doc's checklist, one
Playwright script; reset `notif_seen` in the snapshot first for idempotency).
The session scripts live in the session scratchpad
(`redesign/serve8091.py`, `redesign/capture.py`, `redesign/accept.py`).
