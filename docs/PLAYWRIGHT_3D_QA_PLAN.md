# Playwright 3D QA plan (session 14)

Tooling: venv Playwright (as in all prior QA; the standalone playwright-cli
remains uninstalled/optional — see 3D capability research). Target: the
isolated :8091 instance (worktree code, snapshot data). Results file:
docs/PLAYWRIGHT_3D_QA_RESULTS.md.

## Matrices

**Capture**: 8 routes × 7 viewports (1920×1080, 1600×900, 1440×900,
1366×768, 1280×800, 768×1024, 390×844), before and after, with console /
pageerror / requestfailed listeners and a horizontal-overflow probe on every
load. 200% zoom probes at 960×540 and 683×384.

**Global interaction** (re-run of the session-13 74-check suite): routes +
active nav, skip link, rail keyboard + persistence, drawer focus contract,
notification persistence + intro-once, deep links, masking, mobile drawer,
reduced-motion, no banner stacks.

**3D interaction** (new, via `window.__ops3d` hooks + real DOM):
scene ready flag per page; canvas has role=img + label; node label-twin
buttons tab-focusable; Enter selects (aria-pressed) and opens the panel; Esc
exits focus; camera orbit/zoom clamped (programmatic drag then read rig
limits); Reset restores pose; pause button stops `stats.animating`; hidden
tab pauses; resize keeps aspect (no distortion: project a known node, check
label tracks); mode switcher Scene/Schematic/List swaps without losing the
evidence layer; Live vs Replay badge states; replay scrubber steps events and
never runs while badge says LIVE; low-power toggle drops DPR;
**forced-failure fallback**: init script deletes WebGL contexts → page still
serves Schematic/List with a notice and zero console errors.

**Event truth**: fire a real event into the snapshot DB (insert an
activity_log row through db.log against the snapshot) → live feed delivers
it → packet count increments on the right path — proving no fabricated
traffic (idle scene shows zero packets over a 10 s watch).

**Existing behavior regression**: queue actions, application filters +
record open, submission evidence + safeguards text, inbox reclass, answer
edit + masking, chat composer + proposal confirm requirement, notifications.

## Artifacts

Screenshots + findings JSON stay in the session scratchpad (not committed);
the results doc records the manifest, counts, findings, and the performance
table from docs/3D_PERFORMANCE_PLAN.md methodology.
