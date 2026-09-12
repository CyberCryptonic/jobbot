# Agent Mesh spec — the signature view (session 13)

## Concept

A spatial orchestration instrument: the **Core** (tracker/orchestration state)
at center, agent **pods** clustered by real pipeline role, **flow rails**
between them that light up only when work is actually moving. Below it, the
**operations deck** (cost per agent, submission-head ramp, run timeline,
decision log) supports the same story.

## The Core (original instrument; not a prop)

SVG, ~230px, centered. Three captioned concentric arcs, each a real gauge with
its scale printed beside it:

1. Outer — **auto-applications today vs `daily_target`** (`submit_click` count
   / config value)
2. Middle — **month spend vs `monthly_cap_usd`**
3. Inner — **queue pressure**: manual-queue cards vs `manual_queue_cap`

Center: system state word — AUTONOMOUS / REVIEW HOLD / DRY RUN / PAUSED —
derived from config + state.json, plus jobs-tracked count. Tick marks at
0/50/100%. Arc color: ember; over-cap segment: crit + label. Under
reduced-motion the arcs render at final value with no sweep.

## Pods (differentiated, truthful)

Clusters (desktop, % coordinates; the composition is asymmetric — pod size
reflects role weight):

- ACQUIRE (left): Discovery (large), Scoring
- PRODUCE (top center-right): Letter writer
- EXECUTE (right, large): Submission head — carries the ramp sub-badge
  (`live n/20`, REVIEW HOLD state when self-stopped)
- SENSE (bottom right): Inbox reader, Follow-ups (small)
- INTERFACE (bottom left): Nightly report (small), Chat agent
- Externals (dashed, quiet): Job boards & feeds (far left), Employers / ATS
  (far right), **You** (left center — shows real queue count)

Pod anatomy: state dot + name; role line; status line (`working right now` /
`ran 5:12 PM · ok` / `HOLDING — awaiting your review` / `failed · reason` /
`idle`); **today metric** (real: found / scored / letters / applied / emails
read / drafts / reports / replies); **backlog** where a real backlog exists
(letters pending = queued jobs lacking a letter; queue cards waiting on You);
cost today when non-zero. States map 1:1 to data: `running` (open run_start ≤2h)
· `ok-today` · `fail` (last run failed) · `blocked` (head awaiting review —
Submission only) · `idle`. **No invented latency/health/telemetry; a value the
backend can't provide is simply absent.**

## Flow rails

Path set mirrors the real pipeline: boards→Discovery→Scoring→Letters→
Submission→Employers; Employers→Inbox; Inbox→Follow-ups→Employers; Report→You;
Chat↔You; hub spokes Core↔each agent (faint). Animation classes:
- `.live` (dash-flow): **only while that stage has a run in flight**
- ran-today: static ember-tinted hairline
- idle: quiet titanium hairline
Reduced-motion: `.live` becomes a static bright rail.

## Interaction

- Pods are `<button>`s with full `aria-label` ("Letter writer, ran 5:12 PM,
  ok, 12 letters today, backlog 3, cost $1.00").
- Select → mesh dims (CSS), pod highlighted, **inspection panel** opens beneath
  the mesh (not a modal): health (last run outcome/duration/tokens), current
  backlog, last 8 log rows for that stage, spend today/MTD, next scheduled run,
  error text if the last run failed, links (filter the decision log; jump to
  its page), and the note that state changes go through Chat proposals (the
  only control surface the backend exposes). Esc or "Back to mesh" deselects.
- Filter chips above the mesh: All / Running / Needs attention / Idle
  (dims non-matching pods; list view filters rows).
- **List view toggle**: the same data as an accessible table (also the
  default rendering under 860px — a grouped vertical agent list, never a
  shrunken graph).

## Operations deck (below the mesh)

Row 1: Cost per agent (MTD hbar, validated palette) · Submission-head ramp
panel (live count, target, learned human-verify walls, resume command with
copy). Row 2: run timeline (7 days, AM/PM). Row 3: decision log (filters +
free text + URL params, row expand) — the audit surface, unchanged in
function.

## Data contract

`/api/agents` (extended, all real): per agent `last`, `running`, `today
{metric, decisions, fails}`, `backlog` (letters: queued sans letter & not
thin; others where meaningful), `spend`; `head {…ramp, human_verify_gates,
clicks_today, daily_target}`; `core {applied_today_auto, daily_target,
spend_mtd, cap, queue_count, queue_cap, state}`; `totals`.
