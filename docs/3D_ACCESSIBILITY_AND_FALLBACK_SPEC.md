# 3D accessibility & fallback spec (session 14)

Principle (§19): the WebGL canvas is an **enhancement**; the DOM is the
authoritative interface. Every page keeps its complete session-13 HTML
(tables, cards, filters, editors) as the evidence layer — the 3D scene is
additive and removable.

## The label-twin mechanism

Every selectable 3D node is paired with a real HTML `<button>` in the label
layer over the canvas — the same element is the visible crisp label, the
mouse target, the keyboard tab stop, and the screen-reader surface
(`aria-label` = "name, state, metric", `aria-pressed` for selection). Hover
and `:focus-visible` drive identical scene highlights. Esc exits focus mode.
Because labels are DOM, nothing essential is rendered only inside canvas, and
hover-only information does not exist (labels persist; tooltips echo into the
selection panel).

## Modes per scene (shared switcher)

- **Scene** — WebGL (desktop/laptop default when capable).
- **Schematic** — the page's 2D representation (Agents keeps the entire
  session-13 mesh as its schematic; other pages show their structured 2D
  summary/first content block).
- **List** — the evidence layer alone (tables/cards). Mobile (<900px)
  defaults to List/Schematic; the 3D scene is not shrunk into illegibility.

Canvas gets `role="img"` + a living `aria-label` summary sentence (state
word, counts) refreshed with data; the mode switcher is a real button group.

## Reduced motion

`prefers-reduced-motion: reduce` → EventFeed still updates **state**, but
scenes render single on-demand frames: no packets in flight (paths carry
static count chips), no camera tweens (jumps), no rotation. Verified by test
hook `__ops3d.stats.animating === false`.

## Low-power & failure fallbacks

- Low-power mode (auto when `hardwareConcurrency ≤ 2` or first-frame time
  > 80 ms; manual toggle persisted per device): DPR capped at 1, glow sprites
  off, packet pool halved, on-demand rendering only.
- WebGL unavailable / three.js fails to import / any engine exception: the
  scene host shows a one-line notice and the page runs in Schematic/List —
  nothing else on the page is blocked (dynamic `import()` inside try/catch).
- Hidden tab (`visibilitychange`) and off-screen host (IntersectionObserver)
  pause the loop; resize re-projects labels and re-renders once.

## Keyboard map

Tab through node labels → Enter select/focus → Esc exit focus / close panel →
arrow keys nudge orbit (small, clamped) when the canvas region is focused →
`R` resets the camera (also a visible Reset button). All existing session-13
keyboard behavior (drawer, rails, tables) is unchanged and re-verified.

## Zoom & contrast

200% zoom: verified via 960×540 and 683×384 probes — scene host swaps to
Schematic below its minimum useful size instead of scaling text down. Label
ink and chips reuse the contrast-verified 2D tokens (labels are DOM styled by
the same CSS).
