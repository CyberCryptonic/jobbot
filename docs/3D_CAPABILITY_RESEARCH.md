# 3D capability research (session 14) — extends docs/CAPABILITY_RESEARCH.md

The session-13 research doc remains authoritative for the general roster
(find-skills, Taste, Anthropic frontend-design, Vercel plugin inventory,
web-design-guidelines, Playwright CLI). Statuses re-verified this session and
unchanged: **`find-skills`, Taste, `frontend-design`, and the `playwright-cli`
binary are still not installed**; nothing was silently installed. Their roles
here: harness inventory replaces find-skills; the fetched frontend-design
principles + this directive's own anti-generic rules serve as the Taste-style
critique layer; the fetched Vercel web-interface-guidelines checklist is the
final audit; **venv Playwright** (Microsoft, already in the repo, drives 17
pre-existing tests) performs every browser/QA task the Playwright CLI would.

## 3D-specific capabilities

| Capability | Maintainer / source | State | Decision |
| :--- | :--- | :--- | :--- |
| **three** 0.185.1, `build/three.module.min.js` (357 KB min, MIT) | three.js authors — npm `three` via jsdelivr mirror, license header verified | **VENDORED** at `dashboard/assets/vendor/three.module.min.js` | **USE — mandated by the directive** (§5 names Three.js/WebGL as the implementation and forbids CDN loading, which reads as approval for a local vendored copy; flagged in the final report for confirmation). ES-module build (upstream dropped UMD); loaded via an inline import map + `import()` — still framework-free vanilla JS. Zero runtime network use. |
| OrbitControls / examples jsm | three.js authors | not vendored | **REJECT** — a purpose-built ~90-line camera rig gives the directive's required limits (orbit/zoom clamps, slight pan, reset, focus tween, damping with on-demand render) without example-file plumbing |
| Post-processing stack (EffectComposer, UnrealBloom) | three.js authors | not vendored | **REJECT** — full-screen passes cost the most on integrated graphics; "selective bloom" is achieved with additive-blended sprite glows + emissive materials, which read the same at this scene scale for ~zero cost |
| Line2 fat lines | three.js authors | not vendored | **REJECT** — curved paths are thin `TubeGeometry` (procedural, crisp at any DPR) |
| Physics (cannon/rapier), model loaders (GLTF), texture packs | various | absent | **REJECT** — directive prohibits downloaded cinematic models/unnecessary physics; all geometry is procedural |
| d3-force / force-graph libs | various | absent | **REJECT** — directive forbids force-directed layouts in the final product; layouts are deterministic, hand-placed |
| SSE (server-sent events) | web standard; Flask generator response | built in | **USE** for the one-way live event stream (`/api/events/stream`), with a 3-second polling fallback in the client adapter (guarantees function if any proxy buffers); WebSockets rejected as unneeded per §8 |

Performance guidance consulted at source: threejs.org manual — *rendering on
demand* (render-flag pattern with damping; adopted verbatim in the engine) and
the instancing/lots-of-objects guidance (instanced capsule clusters, pooled
packet meshes). Accessibility baseline: WAI-ARIA dialog/list patterns already
applied in session 13; canvas treated as `role="img"` enhancement with the DOM
as the authoritative surface (§19).

## Compatibility, security, maintenance

Flask + vanilla JS: fully compatible (static ES modules served by the existing
`/assets` route; no build step, no bundler). Runtime network: none (all assets
local; SSE is same-origin). Permissions: none. Security: three.js is MIT,
pinned by content in-repo; no external calls; the WebGL canvas renders only
data already exposed by the JSON API, and untrusted text (postings/emails)
never enters WebGL as anything but escaped HTML labels. Maintenance: one
pinned file; upgrade = replace file. Bundle impact: +357 KB (min) loaded
**lazily only on pages the user opens**, after first paint, cached by the
browser thereafter; measured numbers in docs/3D_PERFORMANCE_PLAN.md results.

## ACTION REQUIRED (unchanged from session 13; nothing blocks this work)

Optional installs still awaiting your word: Anthropic `frontend-design` skill,
`web-design-guidelines` wrapper, Microsoft Playwright CLI (commands in
docs/CAPABILITY_RESEARCH.md). If you *disapprove* of the vendored three.js,
say so and the branch drops to the 2D schematic everywhere (every page keeps
its full 2D interface by design).
