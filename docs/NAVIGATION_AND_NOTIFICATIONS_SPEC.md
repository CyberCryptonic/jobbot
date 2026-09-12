# Navigation & notifications spec (session 13)

## Shell

Two rails, both smoked glass over the void plane.

**Mission rail (left, persistent).** 236px expanded / 72px collapsed (toggle
button, state per-device in localStorage — a device preference, not app data).
Grouped, each item a real `<a>` with glyph + plain label + mono alias
sub-label; collapsed mode keeps labels as `title` + `aria-label` (never an
icon-only guessing game — glyph plus visible tooltip on focus/hover):

- OPERATE — Overview *(Mission Control)* `/` · Queue *(Action Bay)* `/queue` ·
  Inbox *(Signals)* `/inbox`
- RECORDS — Applications *(Pipeline)* `/applications` · Submissions *(Launch
  History)* `/submissions` · Answers *(Knowledge Core)* `/answers`
- SYSTEM — Agents *(Agent Mesh)* `/agent` · Chat *(Copilot)* `/chat`

Route paths and semantics unchanged. Badges: Queue count (ember), Answers open
gaps (amber). Footer: live clock (AM/PM), next scheduled run, `SOC console ·
CT 200`.

**Utility rail (top, sticky, 56px).** Left: current page alias (mono
micro-caps) — the page `<h1>` stays in content. Right cluster: system mode
chip (LIVE / DRY RUN / PAUSED), running-stage chip (only while real), head
ramp chip, spend `$mtd/$cap`, **notification bell**, collapse toggle lives on
the mission rail itself.

**Accessibility.** Skip link to `#main`; landmarks `nav` (labelled) / `banner`
/ `main`; visible focus (2px ember halo) on every interactive element; logical
tab order: skip → rail → utility → content. Mobile (<860px): the mission rail
becomes a **drawer** opened from a menu button in the utility rail (focus
moved in, Esc closes, focus returns) — plus the same single-column content;
no shrunken desktop.

## Notification center

The per-page banner stack is **removed everywhere**. One bell in the utility
rail:

- Bell `aria-label="Notifications: N need you, M unread"`; badge shows
  needs-you count (ember) else unread count (quiet).
- Click/Enter opens a right **slide-over drawer** (`role="dialog"`,
  `aria-modal`, labelled): focus moves to it, Tab cycles inside, Esc or the
  close button dismisses and returns focus to the bell. Background scroll
  locked, `overscroll-behavior: contain`.
- Groups (tablist): **Needs you** · **System** · **History**.
- Item anatomy: severity rail + type tag, title, one-line detail, source page,
  AM/PM time, `Open →` (navigates to the exact record — same deep-link targets
  as before), and the action:
  - Exceptions: **Ack** (server-logged clear, exactly the existing semantics).
  - Advisories: **Mark read** — server-persisted.
- Persistence model (real, not faked): new SQLite table
  `notif_seen(key TEXT PRIMARY KEY, seen_at TEXT)` written via
  `POST /api/notifs/seen`. Every notification carries a stable `key`
  (e.g. `exc-<id>`, `gaps-<max_gap_id>`, `fails-<date>`); a new underlying
  event produces a new key, so genuinely new items re-badge.
- **Needs-you items stay listed until resolved** (ack / gap answered /
  `--reviewed`), even after being read — read state only calms the badge.
- System items, once read, drop out of the badge and collapse under History.
- **First-session system summary**: one `intro` notice (what the system is,
  where things live) with key `intro-v1`; marking it read hides it permanently
  via the same table — it can never reappear on every page.
- History group: derived live from `activity_log` (exception acks, answer-bank
  updates/gap closures, config changes) — a truthful audit trail, no shadow
  store.
- Page-critical load errors remain inline on their page; nothing else repeats
  across routes.

## Deep links (unchanged targets, still verified)

`/applications#app-N` pinned record · `/queue#job-N` flash ·
`/answers#gaps` / `#gap-N` · `/inbox?class=action_needed` ·
`/agent?outcome=fail&date=…` · `/submissions#review`.

## Verification hooks (Playwright)

Bell name/badge; open→focus-in; tab cycle; Esc→focus-return; group tabs;
Mark-read persists across reload (server, not localStorage); intro shows once
ever; needs-you persists while unresolved; no banner stack on any route; rail
collapse/expand keyboard-operable; mobile drawer focus behavior.
