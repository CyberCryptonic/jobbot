# 3D v3 — Final Polish (session 16)

Branch `worktree-design+3d-final-polish-v3` from v2 tip `ef1fc6c`. Where
this disagrees with the v2 doc, this wins. Everything verified on :8091
(snapshot data; prod untouched).

## Palette — the v1 orange identity, restored exactly

Extracted from `efaaa4e` and reapplied verbatim: `--em-1 #FFB27A` (text-safe
accent, links, LIVE, focus), `--em-2 #F08A4B` (primary UI), `--em-3 #D96F2E`
(deep), glow/soft `rgba(240,138,75,.16/.10)`; primary buttons back to the
exact v1 gradient/border/`#FFF7EF`/hover `#F79A5F`. 3D: `PAL.ember/emberHot/
emberDeep/emberDark(0xA8541E, derived: em-3 darkened in-hue for decorative
depth)`; rejections are warm-bronze records `0x9C6B3A`. Semantics: amber
`#FAB219` = waiting (always with a glyph), green = wins only, red `#E23B2E`
= system failures only + symbol (kept from v2 — computed for dark-surface
legibility; v1's `#d03b3b` was dimmer), silver = inbound/calibration, warm
whites for text, graphite/gunmetal structure. v1's electric blues stay
banned (`--data #5B9BE8`, `PAL.ice`, blue s1). Chart series revalidated
blue/purple/pink-free: `#d95926 #199e70 #c98500` (CVD 8.4 / normal 19.8 /
contrast ≥3:1). **Audit:** `scripts/audit_palette.py` scans every hex/rgba
in dashboard CSS/JS/HTML for pink/magenta/purple/electric-blue/bright-cyan
hue bands — clean with an empty allowlist.

## Rendering system

- **Materials:** brushed-metal + floor-panel procedural roughness maps
  (shared 128/256px CanvasTextures, zero downloads, ~80KB VRAM total);
  physical role separation — painted structure, brushed metal, dark metal,
  rubber trim, glass, emissive displays, paper, matte background.
- **Construction:** `bevelBox` (rounded-rect extrusion, bevelled) on every
  major slab — 12 builders chamfer-swept; machines are layered assemblies,
  never naked primitives.
- **Lighting:** hemisphere 2.0 base, warm key 3.2 **with real 1024 PCF-soft
  shadow maps** (tight per-scene frustum via `shadowBounds`, `autoUpdate`
  off — maps refresh only on frames the on-demand loop renders anyway; free
  at idle), neutral fill 1.15, low ember rim, one on-demand ember selection
  point-light, pooled floor light + practicals built into machines. ACES at
  1.34. Low-power mode (auto on ≤2 cores, saved pref, or `?q3d=low`;
  `?q3d=high` forces full) drops shadows/AA/DPR only — the light hierarchy
  survives every mode including reduced motion.
- **Grounding:** soft blob contact shadow under every machine (zero light
  cost), dark service aprons under environments.
- **States:** status ground-halo per machine (idle silver / run ember /
  waiting amber / failed red — steady, no flashing) + label glyphs ▸✓✕! +
  square mini-dots; hover = restrained 2% lift (skipped under reduced
  motion); selected = rim light + bright halo + focus + panel; failed =
  machinery stops (run-gated rotors), red halo, diagnostic reason in the
  label and inspection panel.

## Environments (env kit in ops3d.js)

`wallArc` (curved walls, lit slits, capped), `floorDisc` (paneled disc,
ring channel + embedded ember conduit ring, radial seams, apron),
`floorRect`, `conduit` (recessed data lines), `silhouette` (matte
background machinery), `rail`, `chevrons`, `poolLight`, `blobShadow`.
Per page: circular AI operations chamber (agents — elevated core, radial
stations, sources/employers outside the wall gaps), panoramic command deck
(overview), containment chamber (queue), telemetry receiver room w/ routing
conduits + real classification bays (inbox), dimensional transit facility
w/ six distinct stage gates + guide rails (applications), secure launch
dock w/ gantry (submissions), encrypted archive chamber (answers), operator
alcove (chat). Background always matte, low-contrast, fog-faded.

## Deterministic spacing (§5)

`scratchpad v3/audit_spacing.py`: per node, screen-projected bounds must
not crop or cross the 4% margin, and horizontal-reach footprints must not
intersect pairwise. ALL PASS on all seven scenes at 1600×900; label suite
(zero clipped/overlapping labels, zone captions yield) green at 1920×1080,
1600×900, 1440×900, 1366×768, 1280×720, 1024×768 and 200% zoom.

## Taste critique (redesign-existing-projects @ ccbc156) — v3 pass

Findings fixed during the loop: floors rendered washed-gray under the new
key light (darkened to `0x1f2227`, roughness 0.9) · pool lights z-fought at
y=0 (seated at 0.012) · conduits read as hot copper (cooled to 0.07–0.09) ·
inbox bays undersized with unreadable glyphs (scaled 1.18, emissive 0.55,
row pushed back, receiver label lifted) · front chamber row cropped
(stations pulled in, camera reframed) · queue pod contact shadows merged
into a black band (per-kind blob radius). Remaining rubric departures are
the documented ones (no font swap — pinned fonts; no stock imagery — the
scene is the imagery; no fake data — every number is live).

## three-best-practices audit (emalorenzo skill @ f950f95) — verdicts

- **setup/imports:** import-map + vendored module build ✓ (skill's
  recommended pattern).
- **memory:** full dispose path retained; setData paths dispose replaced
  geometry (budget arc, instanced mesh) ✓.
- **render loop:** on-demand confirmed (`animating:false` at idle; hidden
  tabs pause; damping tween self-terminates) ✓ — the skill's #1 render rule.
- **draw calls / geometry:** shared canvas textures; instanced capsules;
  pooled packets; per-scene draws 24–260 (low-power) / ≤380 (full incl the
  shadow pass), tris 3.7k–105k — inside the skill's guidance for scenes of
  this size. Batching individual halo/label meshes further was considered
  and rejected: per-node materials carry state and stay legible.
- **lights:** 4 static + 1 conditional point vs the "target ≤3" rule —
  accepted deviation, documented: hemisphere is near-free, the rim is 0.5
  intensity with no shadows, and only the key casts.
- **shadows:** single directional caster, 1024 map, tight frustum,
  `autoUpdate=false` ✓ (exactly the skill's static-scene pattern);
  PointLight shadows avoided entirely ✓.
- **transparency:** blob/pool decals are depthWrite-off renderOrder −1;
  glass kept minimal ✓.
- **textures:** 3 shared canvas textures, no loads, no mipmapped monsters ✓.
- **camera/controls:** clamped spherical rig with damping ✓.

## Performance (software floor, this GPU-less LXC)

Routes 38–89 ms; scenes ready 160–318 ms; low-power draws 24–260, tris
3.7k–65k; full mode ≤380 draws / ≤105k tris (shadow pass included); idle
renders nothing; reduced-motion is a static frame; WebGL-off serves the
schematic. Hardware numbers are measured only on the user's machine:
`__ops3d.scenes.agents.stats` + Chrome's FPS meter.

## Safety fix carried in this branch

`pytest.ini` restricts collection to `tests/` — a bare `pytest` can no
longer import the root `test_smtp.py` connection script (which sends a real
email at import). 165 tests collected and passing via plain `pytest`.
