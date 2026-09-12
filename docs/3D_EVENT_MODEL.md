# 3D event model (session 14)

One normalized, read-only event vocabulary drives every scene. Events are
**derived live from `activity_log`** (the audit surface that already records
every decision) — nothing is fabricated; an action with no mapping emits
nothing. The mapping is server-side (`web.py: EVENT_MAP + _normalize_event`)
so all scenes and tests share it.

## Transport

- `GET /api/events?since_id=&limit=&run_id=&application_id=&stage=` —
  normalized events, ascending id. Powers replay (`run_id`), follow-a-job
  (`application_id`), and the polling fallback.
- `GET /api/events/stream?since_id=` — same rows as server-sent events
  (`text/event-stream`), polled from SQLite every 2.5 s server-side with
  heartbeat comments. One-way; user commands stay on the normal JSON API.
- Client adapter (`ops3d.js: EventFeed`): tries SSE, falls back to 3-second
  polling transparently; exposes `mode` (`live` | `replay` | `paused`) and
  never mixes them — replay events carry `replay: true` and the UI badges the
  scene HISTORICAL.

## Mapping (activity_log action → event type)

| Event type | Derived from | Payload |
| :--- | :--- | :--- |
| `run_start` / `run_end` | same actions (stage ∉ ui/system) | stage, outcome, run_id |
| `job_discovered` | `fetch_source` rows | source, count (from detail.found — aggregated, per §16 traffic aggregation) |
| `job_scored` | `score_job` | application_id, subject |
| `job_queued` | `queue_job` | application_id, subject |
| `letter_started` | `letter_requested` | application_id (dashboard-initiated only — batch letters do not log a start; none is invented) |
| `letter_completed` | `letter_written` | application_id, outcome (warn = kept-with-warnings) |
| `submission_prepared` | `form_record` | application_id |
| `submission_waiting_review` | `autosubmit_blocked`, `autosubmit_unknown` | application_id, reason |
| `submission_sent` | `submit_click` (labeled "clicked — confirmation pending" honestly), `manual_applied` | application_id, via |
| `submission_handoff` | `submit_handoff` | application_id |
| `submission_skipped` | `autosubmit_skip`, `skip_job`, `manual_skip` | application_id, reason |
| `email_received` / `email_classified` | `classify_email` (one row → one classified event; class parsed from the reason's leading token, display-only) | class, subject |
| `interview_detected` | `exception_raised` with interview/video type | application_id |
| `action_required` | `exception_raised` (other types), `action_needed` | application_id |
| `followup_scheduled` | `followup_drafted` | application_id |
| `followup_sent` | `followup_sent` — a real emitter exists (`inbox.py` logs it when a follow-up actually sends); no production row yet because sending is draft-gated, so the interface stays silent until one exists (projection covered by `test_followup_sent_projects_when_emitted`) | application_id |
| `report_generated` | `report_sent` | attachments note |
| `agent_warning` | any mapped row with outcome `warn`/`flag` (flag added) | stage, reason |
| `agent_error` | any row with outcome `fail` | stage, reason |

Unmapped actions (stage_summary, screening_answers, research, ui clicks, …)
are intentionally silent — the decision log remains the complete record.

## Scene binding

Each scene declares `{eventType → path(s) + packet style + node flash}`.
Aggregated events (`job_discovered` count=n) render one packet with an n×
count chip, never n meshes. `agent_error` paints the owning node/path red
until the next successful event for that stage. Live vs replay vs paused is a
single adapter state; scenes render the badge from it and never guess.
