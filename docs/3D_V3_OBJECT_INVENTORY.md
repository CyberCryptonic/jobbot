# v3 Object-Quality Inventory (2026-09-01)

Every interactive object, inspected at close range (`acceptance/closeups/`)
and at default camera distance (`acceptance/desk-fold/`, `states/`). Shared
columns: **A11y** = the DOM label twin (button, aria-label with name/state/
metric, glyphed non-color state) plus the schematic/list rows; **States** =
idle/run/ok/blocked/fail via the status ground-halo (silver/ember/amber/red,
steady), hover = 2% mechanical lift + label expand, selected = ember rim
point-light + bright halo + camera focus + inspection panel. Perf cost is
triangles at scale (shadow pass doubles draws in full mode only). Verdict
**FINAL** = no placeholder anywhere; deliberate simplifications are named.

## Agents — circular operations chamber (scene: `agents`)

| Object | Purpose | Geometry & materials | Animation (truthful trigger) | Perf | Evidence | Verdict |
|---|---|---|---|---|---|---|
| JobBot Core | orchestration reactor; the page's center of gravity | chamfered octagonal pedestal + brushed collar, faceted ember heart in a wire cage, 3×8-segment workload rings, budget arc, masted safety beacon; pooled light + blob shadow | heart brightness = autonomy state; spine segments = real queue pressure; budget arc = real month spend; cage turns only while the floor animates; rings spin on run | ~4.8k tri | closeups/agent-core, states/05 | FINAL |
| Discovery | reconnaissance lens | articulated arm on chamfered base, silver-rimmed lens, glow disc | arm sweeps + lens glows only while discovery runs; packet in from boards on real job_discovered | ~1.9k | closeups/agent-discovery | FINAL |
| Scoring | evaluation gauge | drum body, dial face w/ silver calibration arc, ember score fill, needle, 2 comparison rings | needle swings per real job_scored (`act gauge`); rings spin on run | ~2.2k | closeups/agent-scoring | FINAL |
| Letter writer | drafting table | chamfered table + beveled brushed desk, page, 4 line meshes, gantry + stylus w/ ember nib | stylus writes and lines appear ONLY on real letter events | ~2.4k | closeups/agent-materials, video @ stylus | FINAL |
| Submission head | egress checkpoint | chamfered posts + lintel, twin doors, hold lamp, review shield plane, scanner ring, sealed packet | doors open per real send; lamp bright + shield visible only during a real review hold | ~2.6k | closeups/agent-submission, states/01 | FINAL |
| Inbox reader | receiver + sorter | chamfered tray + 3 chutes, mast, dish, feed tip | feed tip flares + chute receive on real email_classified; silver inbound packets | ~2.1k | closeups/agent-inbox | FINAL |
| Follow-ups | timed response loop | rail torus, clock face + hands, dormant rail packet | rail packet orbits once per real followup_sent | ~1.7k | closeups/agent-followup | FINAL |
| Nightly report | audit ledger | chamfered vault base, page stack, stamp arm w/ ember seal, archive slot | stamp falls on real report_generated | ~1.6k | closeups/agent-report | FINAL |
| Chat agent | waveform console | hex plinth, 5 ember waveform bars, proposal slot | bars move only while chatd is actually processing | ~0.9k | closeups/agent-chat | FINAL |
| You (operator) | command station — never an avatar | chamfered desk + legs (rubber trim), 3 ember screens facing the room | blocked state when a real interrupt needs the operator | ~1.1k | closeups/agent-you | FINAL |
| Manual queue | quarantine pods | chamfered tray, 3 glass pods w/ amber lids + latches, warning arc | amber halo/lids while cards truly wait; count in label | ~1.8k | closeups/agent-queue | FINAL |
| Job boards | external feed terminal | chamfered cabinet, silver screen, mast + crossbar (×3 masts at the gap) | source of real discovery packets only | ~0.8k | closeups/agent-boards | FINAL |
| Employers / ATS | secured destination | twin chamfered towers w/ silver screens + arch, rotated toward its gateway | receives real submission packets; silver replies leave from here | ~1.3k | closeups/agent-employers | FINAL |

Environment (non-interactive, matte, fog-faded): segmented floor + conduit
ring + apron, 3 wall arcs w/ lit slits, 5 machinery silhouettes, observation
rail, intake/egress gate posts + chevrons, pooled light ×2, radial conduits
×9. All lower contrast than equipment by construction.

## Other scenes

| Object | Scene | Notes | Evidence | Verdict |
|---|---|---|---|---|
| Round command dais + mini stations | overview | same machine library at 0.85–0.95 scale on a grounded dais, wall + rail + silhouettes behind; real found/applied pillars | desk-fold/overview | FINAL |
| Quarantine pod (single) | queue | chamfered base, glass body, amber lid + latch; per-job scale by fit score; number tag | desk-fold/queue | FINAL |
| Inspection platform | queue | disc + amber review ring, pooled light, release chevrons to the operator console | desk-fold/queue | FINAL |
| Classification bay ×6 | inbox | chamfered pedestal, brushed tray + slot, backboard w/ distinct class glyph (shape ≠ color-only), status lamp | closeups/inbox-* | FINAL |
| Stage gates ×6 | applications | six distinct machines: intake mast, holding clamps + amber bar, stamp arch, scanner ring, interview posts + green lamp, offer arch + beacon | closeups/applications-* | FINAL |
| Transit capsules | applications | instanced, cast shadows, one per real tracked job (cap 40/stage, stated in label) | desk-fold/applications | FINAL |
| Egress gantry + dock | submissions | posts + brushed beam + lamp over the gateway, outbound chevrons, dock wall | desk-fold/submissions | FINAL |
| Vault sectors + index mast | answers | radial sectors (real section sizes), near-closed wall ring, ember-tipped index mast | desk-fold/answers | FINAL |
| Copilot alcove | chat | waveform node in a small dais + backdrop + pool | desk-fold/chat | FINAL |

**Named simplifications (deliberate, not placeholders):** dormant pipeline
records are low flat markers (they are archives, not machinery); background
silhouettes are intentionally crude masses (they must stay background);
the copilot widget stays small because the conversation is the page.
