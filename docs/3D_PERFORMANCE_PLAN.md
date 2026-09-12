# 3D performance plan (session 14)

Budget: the dashboard must stay instant for daily use on modest hardware
(the operator's PC and a folded phone — which gets the 2D modes).

## Rules built into the engine (ops3d.js)

- **Lazy**: three.js + engine load via dynamic `import()` after the page's
  data render; routes never wait on WebGL. One canvas per page.
- **On-demand rendering** (official three.js pattern, render-flag +
  damping-aware): zero RAF while idle; frames only for camera movement,
  in-flight packets, state transitions, hover emphasis.
- **DPR cap** 1.75 (1.0 in low-power). Antialias on (cheap at this scale).
- **Procedural geometry only**; zero texture files; shared materials from one
  library; instanced meshes for capsule clusters; packet meshes pooled and
  reused (pool size 24, aggregation above that).
- **No post-processing chain**; glow = additive sprites + emissive colors.
  No shadow maps. Fog cheap (linear).
- **Pause** on hidden tab and off-screen host; dispose() on page unload and
  mode switch away from Scene (geometries, materials, listeners, observers,
  RAF) — heap checked in QA for leak on repeated mode toggling.
- Draw-call budget per scene ≤ ~120; triangle budget ≤ ~150 k (Agents,
  the richest, targets ≤ 90 k). `__ops3d.stats` exposes renderer.info for
  tests.

## Measurements (methodology)

Playwright, same machine, cold load per route: `navigationStart→load`,
first scene frame time, renderer.info (calls/triangles), JS heap after
settle, and frame-interval sampling during a 30-packet replay burst.
Before = baseline branch point (2D only). Results recorded in
docs/PLAYWRIGHT_3D_QA_RESULTS.md next to the QA matrix.
