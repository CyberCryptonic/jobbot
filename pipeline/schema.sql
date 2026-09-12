-- jobbot schema v1 — five tables.
-- Applied by db.init_db() with CREATE TABLE IF NOT EXISTS semantics (safe to re-run).
-- All timestamps are local America/New_York time as TEXT 'YYYY-MM-DD HH:MM:SS'.

PRAGMA user_version = 1;

-- Every job the system ever sees gets a row and keeps it.
-- "Never re-score a job already in the database" and "why did it skip that one"
-- both depend on skipped/unqueued jobs staying here, not just sent applications.
CREATE TABLE IF NOT EXISTS applications (
    id                INTEGER PRIMARY KEY,
    -- identity / dedup
    company           TEXT NOT NULL,
    role              TEXT NOT NULL,
    location          TEXT,
    company_norm      TEXT NOT NULL,          -- lowercased/stripped; reapply counter groups on this
    title_norm        TEXT NOT NULL,          -- for dedup + Wave-3 title analytics
    dedup_key         TEXT NOT NULL UNIQUE,   -- company_norm|title_norm|location_norm
    url_key           TEXT,                   -- provider-canonical id: 'indeed:jk', 'linkedin:id',
                                              -- 'gh:board:id', ... else sha1 of normalized URL
    -- discovery
    source            TEXT NOT NULL,          -- jobright | company_page | indeed | linkedin | glassdoor | ziprecruiter | manual | seed
    job_url           TEXT,
    posted_date       TEXT,                   -- from the posting; drives the 30-day-old demotion
    first_seen        TEXT NOT NULL,
    last_seen         TEXT NOT NULL,          -- bumped on re-encounter = repost detection
    job_description   TEXT,                   -- raw posting text (treated as untrusted data)
    suspicious        INTEGER NOT NULL DEFAULT 0,  -- 1 = posting contained text addressed to automation
    -- scoring
    fit_score         INTEGER,                -- 0-100
    tier              TEXT CHECK (tier IN ('A','B','C')),
    salary_posted     TEXT,                   -- raw, as listed
    salary_min        INTEGER,                -- parsed USD/yr (nullable)
    salary_max        INTEGER,
    apply_route       TEXT CHECK (apply_route IN ('ats','native','direct')),
    -- materials
    cover_letter_path TEXT,
    screening_answers TEXT,                   -- JSON list [{"q":..., "a":..., "source":"answer file section"}]
    company_research  TEXT,                   -- short brief used for the letter (Wave-2 kanban card)
    -- lifecycle
    status            TEXT NOT NULL DEFAULT 'discovered' CHECK (status IN
                      ('discovered','queued','applied','screening','interview',
                       'offer','rejected','ghosted','skipped')),
    date_applied      TEXT,
    last_update       TEXT NOT NULL,
    next_action       TEXT,
    letter_required   INTEGER,                  -- Layer 6 signal: 1 form has a cover-letter field, 0 it does not, NULL unknown
    form_probed_at    TEXT,                     -- when the application form was last read
    submission_path   TEXT,                     -- submissions/YYYY-MM-DD/{id}.json — the packet (dry-run or real)
    carried_over      INTEGER NOT NULL DEFAULT 0,  -- days rolled forward in the manual queue
    contact_email     TEXT,                     -- Layer 7: a human/company reply address seen on employer mail (never a noreply)
    followup_1_sent   TEXT,                     -- Layer 7: when the day-7 follow-up went out
    followup_2_sent   TEXT,                     -- Layer 7: when the day-14 follow-up went out
    run_id            TEXT,                   -- discovery run that created the row
    -- exception queue (one open exception per job; ack clears it and logs)
    exception_type    TEXT CHECK (exception_type IN
                      ('interview','assessment','video_interview','signature')),
    exception_note    TEXT,
    exception_raised_at TEXT,
    notes             TEXT                    -- one-sentence score reason lives here
);

CREATE INDEX IF NOT EXISTS idx_app_status   ON applications(status);
CREATE INDEX IF NOT EXISTS idx_app_company  ON applications(company_norm);
CREATE INDEX IF NOT EXISTS idx_app_score    ON applications(fit_score DESC);
CREATE INDEX IF NOT EXISTS idx_app_applied  ON applications(date_applied);
CREATE INDEX IF NOT EXISTS idx_app_exception ON applications(exception_type)
    WHERE exception_type IS NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS idx_app_urlkey ON applications(url_key)
    WHERE url_key IS NOT NULL;

-- The table everything downstream writes. Contract:
-- every scheduled run wraps itself in db.Run(stage), which writes a run_start row,
-- one row per decision, and ALWAYS a run_end row (outcome='fail' + traceback on crash).
-- The Agent view timeline is built from run_start/run_end pairs; the decision log
-- is everything in between.
CREATE TABLE IF NOT EXISTS activity_log (
    id             INTEGER PRIMARY KEY,
    ts             TEXT NOT NULL,
    run_id         TEXT NOT NULL,             -- 'YYYYMMDD-HHMMSS-stage', sortable and greppable
    stage          TEXT NOT NULL,             -- discovery|scoring|materials|submission|inbox|followup|report|chat|ui|system
    action         TEXT NOT NULL,             -- run_start|run_end|score_job|skip_job|submit|classify_email|...
    subject        TEXT,                      -- human-readable target: 'Meridian Health — SOC Analyst I'
    application_id INTEGER REFERENCES applications(id),
    outcome        TEXT NOT NULL CHECK (outcome IN ('ok','skip','warn','fail','flag')),
    reason         TEXT,                      -- the one-sentence why
    detail         TEXT,                      -- optional JSON / error excerpt (free-text searched)
    duration_ms    INTEGER NOT NULL DEFAULT 0,
    tokens_used    INTEGER NOT NULL DEFAULT 0,  -- total tokens behind this row (in+out+cache)
    cost_usd       REAL    NOT NULL DEFAULT 0,  -- exact dollars, computed at write time from pinned rates
    token_detail   TEXT                       -- JSON {"in":..,"out":..,"cache_read":..,"cache_write":..}
);

CREATE INDEX IF NOT EXISTS idx_log_ts      ON activity_log(ts);
CREATE INDEX IF NOT EXISTS idx_log_run     ON activity_log(run_id);
CREATE INDEX IF NOT EXISTS idx_log_stage   ON activity_log(stage, ts);
CREATE INDEX IF NOT EXISTS idx_log_app     ON activity_log(application_id);
CREATE INDEX IF NOT EXISTS idx_log_bad     ON activity_log(outcome)
    WHERE outcome IN ('fail','warn','flag');

-- Chat command queue: page writes pending -> chatd polls every 3s -> executes ->
-- reply lands in chat_messages -> marked done. Dashboard buttons do NOT go through
-- here (they hit the API directly); this is the chat path only.
CREATE TABLE IF NOT EXISTS commands (
    id           INTEGER PRIMARY KEY,
    created_at   TEXT NOT NULL,
    source       TEXT NOT NULL DEFAULT 'chat',   -- 'chat' only (trigger-enforced)
    command      TEXT NOT NULL,                  -- raw chat text
    status       TEXT NOT NULL DEFAULT 'pending'
                 CHECK (status IN ('pending','running','done','failed')),
    picked_up_at TEXT,
    finished_at  TEXT,
    error        TEXT
);

CREATE INDEX IF NOT EXISTS idx_cmd_pending ON commands(status) WHERE status = 'pending';

-- Layer 9 boundary: the only legitimate writer of commands is web.py's
-- POST /api/chat (source='chat', <= 4000 chars, one chat_messages user row
-- written in the same call). These triggers reject anything else at the
-- database, so no cron job or scraped-text code path can queue a command
-- for the tool-calling daemon even by accident.
CREATE TRIGGER IF NOT EXISTS trg_commands_chat_only
BEFORE INSERT ON commands
BEGIN
    SELECT CASE
        WHEN NEW.source != 'chat' THEN RAISE(ABORT, 'commands: only the chat UI may insert (source must be chat)')
        WHEN length(NEW.command) > 4000 THEN RAISE(ABORT, 'commands: text over 4000 chars')
        WHEN length(trim(NEW.command)) = 0 THEN RAISE(ABORT, 'commands: empty text')
    END;
END;
CREATE TRIGGER IF NOT EXISTS trg_commands_no_edit_text
BEFORE UPDATE OF command, source, created_at ON commands
BEGIN
    SELECT RAISE(ABORT, 'commands: text and provenance are immutable');
END;

-- Layer 9: a proposed state change. The model can only create one of these
-- (via chatd); it is applied by plain code when the operator's own next chat
-- message is 'confirm <id>'. Nothing the model reads can apply a proposal.
CREATE TABLE IF NOT EXISTS chat_proposals (
    id          INTEGER PRIMARY KEY,
    created_at  TEXT NOT NULL,
    command_id  INTEGER NOT NULL REFERENCES commands(id),
    tool        TEXT NOT NULL,
    args        TEXT NOT NULL,                  -- JSON, exactly what will be applied
    summary     TEXT NOT NULL,                  -- one line shown on the Confirm button
    status      TEXT NOT NULL DEFAULT 'pending'
                CHECK (status IN ('pending','applied','cancelled','expired','failed')),
    resolved_at TEXT,
    result      TEXT                            -- what happened when applied (or the error)
);

-- Layer 9: draft_email output. The daemon writes drafts; only the dashboard's
-- Send button (POST /api/drafts/<id>/send, the operator's click) sends one.
CREATE TABLE IF NOT EXISTS email_drafts (
    id          INTEGER PRIMARY KEY,
    created_at  TEXT NOT NULL,
    command_id  INTEGER REFERENCES commands(id),
    application_id INTEGER REFERENCES applications(id),
    to_addr     TEXT NOT NULL,
    subject     TEXT NOT NULL,
    body        TEXT NOT NULL,
    status      TEXT NOT NULL DEFAULT 'draft' CHECK (status IN ('draft','sent','discarded')),
    sent_at     TEXT,
    error       TEXT
);

CREATE TABLE IF NOT EXISTS chat_messages (
    id         INTEGER PRIMARY KEY,
    ts         TEXT NOT NULL,
    role       TEXT NOT NULL CHECK (role IN ('user','assistant','system')),
    content    TEXT NOT NULL,
    command_id INTEGER REFERENCES commands(id),  -- ties both sides of an exchange to its command
    tool_calls TEXT,                             -- JSON audit of tools the reply used (Layer 9)
    turns      TEXT                              -- JSON: the assistant/tool_result blocks behind this reply, replayed as history
);

CREATE INDEX IF NOT EXISTS idx_chat_ts ON chat_messages(id);

-- Screening questions the answer file couldn't cover. Deduped on a normalized
-- copy of the question so 12 postings asking the same thing = one row, counted.
CREATE TABLE IF NOT EXISTS answer_gaps (
    id            INTEGER PRIMARY KEY,
    created_at    TEXT NOT NULL,
    question      TEXT NOT NULL,               -- as the form asked it
    question_norm TEXT NOT NULL UNIQUE,
    times_seen    INTEGER NOT NULL DEFAULT 1,
    last_seen     TEXT NOT NULL,
    first_application_id INTEGER REFERENCES applications(id),
    status        TEXT NOT NULL DEFAULT 'open' CHECK (status IN ('open','answered','dismissed')),
    answer        TEXT,
    resolved_at   TEXT
);

-- Layer 7: every inbox message the classifier has looked at, exactly once.
-- uid is the mailbox's IMAP UID (stable per mailbox). class is what the pipeline
-- believes; class_override is the operator's correction from the Inbox page
-- (the effective class is COALESCE(class_override, class)). applied_at marks
-- when the tracker was updated from this row; NULL while in dry run.
CREATE TABLE IF NOT EXISTS inbox_messages (
    id              INTEGER PRIMARY KEY,
    uid             INTEGER NOT NULL UNIQUE,
    msg_ts          TEXT NOT NULL,               -- email Date, local time
    seen_ts         TEXT NOT NULL,               -- when the classifier read it
    from_addr       TEXT NOT NULL,
    subject         TEXT,
    class           TEXT NOT NULL CHECK (class IN
                    ('confirmation','rejection','interview','offer','action_needed','noise')),
    kind            TEXT,                        -- sub-type: alert|marketing|account|assessment|video_interview|signature|info_request|incomplete|scheduling|...
    company         TEXT,
    role            TEXT,
    deadline        TEXT,
    summary         TEXT,
    confidence      REAL,
    method          TEXT NOT NULL,               -- rule | model
    application_id  INTEGER REFERENCES applications(id),
    match_how       TEXT,                        -- how the tracker row was matched (or 'none')
    suspicious      INTEGER NOT NULL DEFAULT 0,  -- text addressed to an automated system
    class_override  TEXT CHECK (class_override IN
                    ('confirmation','rejection','interview','offer','action_needed','noise')),
    applied_at      TEXT,
    excerpt         TEXT                         -- first ~600 chars of body text (untrusted, for review)
);
CREATE INDEX IF NOT EXISTS idx_inbox_ts ON inbox_messages(msg_ts);
CREATE INDEX IF NOT EXISTS idx_inbox_app ON inbox_messages(application_id);

-- Notification read-state for the dashboard's notification center (session 13).
-- One row per notification key the operator marked read; keys are minted from
-- the underlying event (exc-<id>, gaps-<max id>, fails-<date>, intro-v1) so a
-- new event re-badges. web.py also lazily creates this for older databases.
CREATE TABLE IF NOT EXISTS notif_seen (
    key     TEXT PRIMARY KEY,
    seen_at TEXT NOT NULL
);
