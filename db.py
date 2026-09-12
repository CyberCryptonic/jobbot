"""jobbot data access layer.

Every part of the pipeline — cron jobs, the web API, chatd, seed — goes through
this module. It is stdlib-only on purpose so plain-Python cron jobs can import it
without a virtualenv.

Quick use from the CLI:

    python3 -c "import db; db.init_db(); print('schema ok at', db.DB_PATH)"
    python3 -c "import db; print(db.export_csv())"

Logging contract (the part to get right):

    with db.Run('discovery') as run:
        run.log('fetch_source', subject='jobright', outcome='ok',
                reason='34 postings', duration_ms=8400)
        run.log('score_job', subject='Acme — SOC Analyst I', application_id=7,
                outcome='ok', reason='Tier A title, on-prem SOC, 82',
                duration_ms=2100, **db.usage(tokens_in=900, tokens_out=140))

Run writes a run_start row on entry and ALWAYS a run_end row on exit — outcome
'fail' with a traceback excerpt if the job crashed — so the Agent view timeline
never shows a silent hole. Token totals and cost roll up onto run_end.
"""

import csv
import json
import re
import sqlite3
import time
import traceback
import unicodedata
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

BASE_DIR = Path(__file__).resolve().parent
TZ = ZoneInfo("America/New_York")

# ---------------------------------------------------------------------------
# .env — same parsing pattern as test_smtp.py. Values never get printed/logged.
# ---------------------------------------------------------------------------

def load_env(path=BASE_DIR / ".env"):
    """Missing .env returns {} so a fresh clone can import db and run
    `db.init_db()` before any credentials exist."""
    env = {}
    if not Path(path).exists():
        return env
    for line in Path(path).read_text().splitlines():
        line = line.strip()
        if "=" in line and not line.startswith("#"):
            k, v = line.split("=", 1)
            env[k] = v
    return env

ENV = load_env()
DB_PATH = ENV.get("DB_PATH") or str(BASE_DIR / "jobbot.db")
CONFIG_PATH = BASE_DIR / "config.json"   # chatd tests point this at a copy
RESUME_PATH = Path(ENV.get("RESUME_PATH") or BASE_DIR / "resume.pdf")

def identity():
    """identity.json as a dict, {} when absent or invalid. The strict loader
    (mode check, email-matches-mailbox check) is autosubmit.load_identity;
    this one is for display strings only."""
    try:
        return json.loads((BASE_DIR / "identity.json").read_text())
    except (OSError, ValueError):
        return {}

def applicant_name():
    """Full name from identity.json, else the mailbox address, else ''."""
    ident = identity()
    name = " ".join(x for x in (ident.get("first_name"), ident.get("last_name")) if x)
    return name or ENV.get("MAIL_ADDRESS", "")

# ---------------------------------------------------------------------------
# Model pricing — claude-sonnet-4-5-20250929, USD per million tokens.
# Verified against platform.claude.com/docs/en/about-claude/pricing 2026-08-27.
# cost_usd on activity_log rows is computed from these at write time so the
# dashboard's spend counters reconcile against the Anthropic console.
# ---------------------------------------------------------------------------

MODEL = "claude-sonnet-4-5-20250929"
PRICE_PER_MTOK = {
    "in": 3.00,             # base input
    "out": 15.00,           # output
    "cache_write": 3.75,    # 5-minute cache write (the default TTL)
    "cache_write_1h": 6.00, # 1-hour cache write
    "cache_read": 0.30,     # cache hit / refresh
}

def usage(tokens_in=0, tokens_out=0, cache_read=0, cache_write=0, cache_write_1h=0):
    """Turn an API response's token counts into the three log fields.

    Returns a dict meant to be splatted into log()/Run.log():
    tokens_used (total), cost_usd (exact), token_detail (JSON split).
    """
    cost = (
        tokens_in * PRICE_PER_MTOK["in"]
        + tokens_out * PRICE_PER_MTOK["out"]
        + cache_read * PRICE_PER_MTOK["cache_read"]
        + cache_write * PRICE_PER_MTOK["cache_write"]
        + cache_write_1h * PRICE_PER_MTOK["cache_write_1h"]
    ) / 1_000_000
    total = tokens_in + tokens_out + cache_read + cache_write + cache_write_1h
    detail = {"in": tokens_in, "out": tokens_out}
    if cache_read:
        detail["cache_read"] = cache_read
    if cache_write:
        detail["cache_write"] = cache_write
    if cache_write_1h:
        detail["cache_write_1h"] = cache_write_1h
    return {
        "tokens_used": total,
        "cost_usd": round(cost, 6),
        "token_detail": json.dumps(detail),
    }

# ---------------------------------------------------------------------------
# Time — local America/New_York, one TEXT format everywhere.
# ---------------------------------------------------------------------------

FMT = "%Y-%m-%d %H:%M:%S"

def now():
    return datetime.now(TZ).strftime(FMT)

def today():
    return datetime.now(TZ).strftime("%Y-%m-%d")

def days_ago(n):
    return (datetime.now(TZ) - timedelta(days=n)).strftime("%Y-%m-%d")

# ---------------------------------------------------------------------------
# Connections
# ---------------------------------------------------------------------------

def connect():
    """WAL + busy_timeout so cron writers, the web API and chatd share the file.

    autocommit (isolation_level=None): every write lands immediately. Python's
    default would hold an implicit transaction open until .commit(), and a
    long-lived connection holding a write lock starves the other processes.
    """
    conn = sqlite3.connect(DB_PATH, timeout=10, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn

def migrate():
    """Add columns introduced after schema v1 to an existing database (idempotent)."""
    conn = connect()
    have = {r[1] for r in conn.execute("PRAGMA table_info(applications)")}
    for col, ddl in (("letter_required", "INTEGER"), ("form_probed_at", "TEXT"),
                     ("submission_path", "TEXT"), ("contact_email", "TEXT"),
                     ("followup_1_sent", "TEXT"), ("followup_2_sent", "TEXT")):
        if col not in have:
            conn.execute(f"ALTER TABLE applications ADD COLUMN {col} {ddl}")
    have = {r[1] for r in conn.execute("PRAGMA table_info(chat_messages)")}
    if "turns" not in have:
        conn.execute("ALTER TABLE chat_messages ADD COLUMN turns TEXT")
    # tables added after v1 (CREATE IF NOT EXISTS is idempotent)
    conn.executescript((BASE_DIR / "schema.sql").read_text())
    conn.close()

def init_db():
    conn = connect()
    conn.executescript((BASE_DIR / "schema.sql").read_text())
    conn.commit()
    conn.close()

# ---------------------------------------------------------------------------
# Normalization + dedup. Same req shows up on three boards routinely; match on
# company + normalized title + location so duplicate rows don't wreck funnel math.
# ---------------------------------------------------------------------------

def norm(s):
    if not s:
        return ""
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode()
    s = s.lower().replace("&", " and ")
    s = re.sub(r"[^a-z0-9 ]+", " ", s)
    return re.sub(r"\s+", " ", s).strip()

def make_dedup_key(company, role, location):
    return f"{norm(company)}|{norm(role)}|{norm(location)}"

# ---------------------------------------------------------------------------
# activity_log
# ---------------------------------------------------------------------------

def log(stage, action, *, run_id, subject=None, application_id=None,
        outcome="ok", reason=None, detail=None, duration_ms=0,
        tokens_used=0, cost_usd=0.0, token_detail=None, ts=None, conn=None):
    """Write one decision row. Pass ts only when backdating (seed data)."""
    own = conn is None
    if own:
        conn = connect()
    conn.execute(
        """INSERT INTO activity_log
           (ts, run_id, stage, action, subject, application_id, outcome, reason,
            detail, duration_ms, tokens_used, cost_usd, token_detail)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (ts or now(), run_id, stage, action, subject, application_id, outcome,
         reason, detail, int(duration_ms), int(tokens_used), float(cost_usd),
         token_detail),
    )
    if own:
        conn.commit()
        conn.close()

class Run:
    """Context manager for one scheduled run. See module docstring."""

    def __init__(self, stage, conn=None):
        self.stage = stage
        self.run_id = f"{datetime.now(TZ).strftime('%Y%m%d-%H%M%S')}-{stage}"
        self.conn = conn or connect()
        self._own_conn = conn is None
        self._t0 = None
        self.tokens = 0
        self.cost = 0.0

    def __enter__(self):
        self._t0 = time.monotonic()
        log(self.stage, "run_start", run_id=self.run_id, outcome="ok",
            conn=self.conn)
        self.conn.commit()
        return self

    def log(self, action, **kw):
        self.tokens += kw.get("tokens_used", 0)
        self.cost += kw.get("cost_usd", 0.0)
        log(self.stage, action, run_id=self.run_id, conn=self.conn, **kw)
        self.conn.commit()

    def __exit__(self, exc_type, exc, tb):
        dur = int((time.monotonic() - self._t0) * 1000)
        if exc_type is None:
            log(self.stage, "run_end", run_id=self.run_id, outcome="ok",
                duration_ms=dur, tokens_used=self.tokens,
                cost_usd=round(self.cost, 6), conn=self.conn)
        else:
            excerpt = "".join(traceback.format_exception(exc_type, exc, tb))[-1500:]
            log(self.stage, "run_end", run_id=self.run_id, outcome="fail",
                reason=f"{exc_type.__name__}: {exc}", detail=excerpt,
                duration_ms=dur, tokens_used=self.tokens,
                cost_usd=round(self.cost, 6), conn=self.conn)
        self.conn.commit()
        if self._own_conn:
            self.conn.close()
        return False  # never swallow the exception; cron sees a nonzero exit

# ---------------------------------------------------------------------------
# applications
# ---------------------------------------------------------------------------

def upsert_job(conn, *, company, role, location=None, source, job_url=None,
               url_key=None, posted_date=None, job_description=None,
               salary_posted=None, salary_min=None, salary_max=None,
               apply_route=None, run_id=None, ts=None):
    """Insert a newly discovered job, or bump last_seen if we already have it.

    Dedup precedence: url_key (provider-canonical id) first, then
    company|title|location. Returns (id, is_new). Never touches an existing
    row's score — jobs already in the database are never re-scored. A
    re-encounter fills in fields the existing row is missing (description,
    route, salary, canonical URL) but never overwrites what's already there.
    """
    t = ts or now()
    key = make_dedup_key(company, role, location)
    row = None
    if url_key:
        row = conn.execute(
            "SELECT * FROM applications WHERE url_key=?", (url_key,)).fetchone()
    if row is None:
        row = conn.execute(
            "SELECT * FROM applications WHERE dedup_key=?", (key,)).fetchone()
    if row:
        sets, vals = ["last_seen=?"], [t]
        for col, new in (("job_url", job_url), ("url_key", url_key),
                         ("job_description", job_description),
                         ("salary_posted", salary_posted),
                         ("salary_min", salary_min), ("salary_max", salary_max),
                         ("apply_route", apply_route),
                         ("posted_date", posted_date)):
            if new is not None and row[col] is None:
                sets.append(f"{col}=?")
                vals.append(new)
        vals.append(row["id"])
        try:
            conn.execute(f"UPDATE applications SET {', '.join(sets)} WHERE id=?", vals)
        except sqlite3.IntegrityError:
            # url_key already on another row (same posting, different listing
            # text) — just bump last_seen on this one
            conn.execute("UPDATE applications SET last_seen=? WHERE id=?",
                         (t, row["id"]))
        return row["id"], False
    cur = conn.execute(
        """INSERT INTO applications
           (company, role, location, company_norm, title_norm, dedup_key,
            url_key, source, job_url, posted_date, first_seen, last_seen,
            job_description, salary_posted, salary_min, salary_max,
            apply_route, status, last_update, run_id)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,'discovered',?,?)""",
        (company, role, location, norm(company), norm(role), key, url_key,
         source, job_url, posted_date, t, t, job_description, salary_posted,
         salary_min, salary_max, apply_route, t, run_id),
    )
    return cur.lastrowid, True

def set_status(conn, app_id, status, *, ts=None, next_action=None,
               append_note=None):
    """Move a job through the funnel. Sets date_applied on 'applied'."""
    t = ts or now()
    sets, vals = ["status=?", "last_update=?"], [status, t]
    if status == "applied":
        sets.append("date_applied=COALESCE(date_applied, ?)")
        vals.append(t)
    if next_action is not None:
        sets.append("next_action=?")
        vals.append(next_action)
    if append_note:
        sets.append("notes=COALESCE(notes || char(10), '') || ?")
        vals.append(append_note)
    vals.append(app_id)
    conn.execute(f"UPDATE applications SET {', '.join(sets)} WHERE id=?", vals)

def subject_of(conn, app_id):
    r = conn.execute(
        "SELECT company, role FROM applications WHERE id=?", (app_id,)
    ).fetchone()
    return f"{r['company']} — {r['role']}" if r else f"application #{app_id}"

def reapply_counts(conn):
    """Applications actually sent, per company. Warn at 2, block at 3."""
    rows = conn.execute(
        """SELECT company_norm, COUNT(*) AS n FROM applications
           WHERE status IN ('applied','screening','interview','offer','rejected','ghosted')
           GROUP BY company_norm"""
    ).fetchall()
    return {r["company_norm"]: r["n"] for r in rows}

def manual_queue(conn):
    return conn.execute(
        """SELECT * FROM applications
           WHERE status='queued' AND apply_route='native'
             AND (next_action IS NULL OR next_action NOT LIKE 'DRY-RUN%')
           ORDER BY fit_score DESC"""
    ).fetchall()

# ---------------------------------------------------------------------------
# Exceptions — the only four interrupts. One open exception per job.
# ---------------------------------------------------------------------------

def raise_exception(conn, app_id, ex_type, note, *, run_id, stage, ts=None):
    t = ts or now()
    conn.execute(
        """UPDATE applications SET exception_type=?, exception_note=?,
           exception_raised_at=?, last_update=? WHERE id=?""",
        (ex_type, note, t, t, app_id),
    )
    log(stage, "exception_raised", run_id=run_id, subject=subject_of(conn, app_id),
        application_id=app_id, outcome="flag", reason=f"{ex_type}: {note}",
        ts=t, conn=conn)

def ack_exception(conn, app_id, *, run_id, ts=None):
    t = ts or now()
    row = conn.execute(
        "SELECT exception_type, exception_note FROM applications WHERE id=?",
        (app_id,),
    ).fetchone()
    conn.execute(
        """UPDATE applications SET exception_type=NULL, exception_note=NULL,
           exception_raised_at=NULL, last_update=? WHERE id=?""",
        (t, app_id),
    )
    if row and row["exception_type"]:
        log("ui", "exception_ack", run_id=run_id, subject=subject_of(conn, app_id),
            application_id=app_id, outcome="ok",
            reason=f"acknowledged {row['exception_type']}: {row['exception_note']}",
            ts=t, conn=conn)

def open_exceptions(conn):
    return conn.execute(
        """SELECT id, company, role, exception_type, exception_note,
                  exception_raised_at
           FROM applications WHERE exception_type IS NOT NULL
           ORDER BY exception_raised_at"""
    ).fetchall()

# ---------------------------------------------------------------------------
# Maintenance — wired to the schedule when Layer 8 lands.
# ---------------------------------------------------------------------------

def ghost_stale(conn, *, run_id, days=30):
    """Auto-ghost applications with no movement for `days` days."""
    cutoff = (datetime.now(TZ) - timedelta(days=days)).strftime(FMT)
    rows = conn.execute(
        """SELECT id, company, role FROM applications
           WHERE status IN ('applied','screening') AND last_update < ?""",
        (cutoff,),
    ).fetchall()
    for r in rows:
        set_status(conn, r["id"], "ghosted",
                   append_note=f"auto-ghosted after {days} days without response")
        log("system", "auto_ghost", run_id=run_id,
            subject=f"{r['company']} — {r['role']}", application_id=r["id"],
            outcome="ok", reason=f"no response in {days} days", conn=conn)
    return len(rows)

def source_health(conn):
    """Per discovery source: latest run's found-count vs the run before it.
    Powers the Overview health table and the nightly report's source check.
    'found' None means the source was disabled/skipped that run."""
    rows = conn.execute(
        "SELECT subject, ts, detail, outcome FROM activity_log "
        "WHERE action='fetch_source' ORDER BY id DESC LIMIT 80").fetchall()
    out = {}
    for r in rows:
        s = r["subject"]
        try:
            found = json.loads(r["detail"] or "{}").get("found")
        except ValueError:
            found = None
        if s not in out:
            out[s] = {"source": s, "last_ts": r["ts"], "found": found,
                      "outcome": r["outcome"], "prev": "?"}
        elif out[s]["prev"] == "?":
            out[s]["prev"] = found
    for v in out.values():
        if v["prev"] == "?":
            v["prev"] = None
    return sorted(out.values(), key=lambda v: v["source"])


def export_csv(out_dir=BASE_DIR / "exports"):
    """Nightly CSV export of the applications table."""
    out_dir = Path(out_dir)
    out_dir.mkdir(exist_ok=True)
    path = out_dir / f"applications-{today()}.csv"
    conn = connect()
    rows = conn.execute("SELECT * FROM applications ORDER BY id").fetchall()
    with open(path, "w", newline="") as f:
        if rows:
            w = csv.writer(f)
            w.writerow(rows[0].keys())
            w.writerows([tuple(r) for r in rows])
    conn.close()
    return str(path)

# ---------------------------------------------------------------------------
# Chat + commands + answer gaps
# ---------------------------------------------------------------------------

def add_command(conn, command, source="chat", ts=None):
    cur = conn.execute(
        "INSERT INTO commands (created_at, source, command) VALUES (?,?,?)",
        (ts or now(), source, command),
    )
    return cur.lastrowid

def add_chat(conn, role, content, command_id=None, tool_calls=None, ts=None, turns=None):
    cur = conn.execute(
        """INSERT INTO chat_messages (ts, role, content, command_id, tool_calls, turns)
           VALUES (?,?,?,?,?,?)""",
        (ts or now(), role, content, command_id, tool_calls, turns),
    )
    return cur.lastrowid

def next_pending_command(conn):
    return conn.execute(
        "SELECT * FROM commands WHERE status='pending' ORDER BY id LIMIT 1"
    ).fetchone()

def chat_history(conn, max_messages=30, max_age_hours=24):
    """User/assistant text since the last 'session reset' system row, newest
    `max_messages` within `max_age_hours`, oldest first. This is the only
    conversation memory chatd replays; tool-call blocks are not replayed."""
    reset = conn.execute(
        "SELECT id FROM chat_messages WHERE role='system' AND content LIKE 'session reset%' "
        "ORDER BY id DESC LIMIT 1").fetchone()
    since_id = reset["id"] if reset else 0
    cutoff = (datetime.now(TZ) - timedelta(hours=max_age_hours)).strftime(FMT)
    rows = conn.execute(
        "SELECT id, role, content, command_id, tool_calls, turns FROM chat_messages WHERE id > ? AND ts >= ? "
        "AND role IN ('user','assistant') ORDER BY id DESC LIMIT ?",
        (since_id, cutoff, max_messages)).fetchall()
    return [dict(r) for r in reversed(rows)]

def open_gaps(conn):
    return [dict(r) for r in conn.execute(
        "SELECT id, question, times_seen, last_seen, first_application_id FROM answer_gaps "
        "WHERE status='open' ORDER BY times_seen DESC, last_seen DESC")]

def add_proposal(conn, command_id, tool, args, summary):
    cur = conn.execute(
        "INSERT INTO chat_proposals (created_at, command_id, tool, args, summary) VALUES (?,?,?,?,?)",
        (now(), command_id, tool, json.dumps(args), summary))
    return cur.lastrowid

def pending_proposals(conn, max_age_minutes=30):
    """Open proposals; anything older than max_age_minutes is expired first."""
    cutoff = (datetime.now(TZ) - timedelta(minutes=max_age_minutes)).strftime(FMT)
    conn.execute("UPDATE chat_proposals SET status='expired', resolved_at=? "
                 "WHERE status='pending' AND created_at < ?", (now(), cutoff))
    return [dict(r) for r in conn.execute(
        "SELECT * FROM chat_proposals WHERE status='pending' ORDER BY id")]

def resolve_proposal(conn, pid, status, result=None):
    conn.execute("UPDATE chat_proposals SET status=?, resolved_at=?, result=? WHERE id=?",
                 (status, now(), result, pid))

def pipeline_paused():
    """The chat agent's pause flag (config.json -> pipeline.paused). Returns the
    pipeline block when paused, else None. Read fresh each call."""
    try:
        cfg = json.loads(Path(CONFIG_PATH).read_text()).get("pipeline", {})
    except (OSError, ValueError):
        return None
    return cfg if cfg.get("paused") else None

PAUSE_FILE = BASE_DIR / "PAUSE"

def kill_switch():
    """Operator kill switch: the file ~/jobbot/PAUSE exists. Checked before any
    API call or outside action; `touch PAUSE` stops everything, `rm PAUSE` resumes.
    Independent of config.json so it works even if the config is broken."""
    return PAUSE_FILE.exists()

def halt_if_paused(stage):
    """Every stage calls this first. Returns True (and the caller must return
    at once) when the PAUSE file exists or the chat pause flag is set. Logs one
    run_start / kill_switch_skip (or paused_skip) / run_end triple so the
    Agent view shows the hole and why. No API call, no other side effect."""
    if kill_switch():
        with Run(stage) as run:
            run.log("kill_switch_skip", outcome="skip",
                    reason=f"PAUSE file present ({PAUSE_FILE}); stage exited before doing anything")
        print(f"{stage}: PAUSE file present, exiting")
        return True
    if pipeline_paused():
        paused_run(stage)
        return True
    return False

def paused_run(stage):
    """A cron job that finds the pipeline paused logs one run_start / paused_skip /
    run_end triple and exits 0, so the Agent view shows the hole and why."""
    p = pipeline_paused()
    with Run(stage) as run:
        run.log("paused_skip", outcome="skip",
                reason=f"pipeline paused since {p.get('since')} ({p.get('by')}): {p.get('reason') or 'no reason given'}")

def upsert_answer_gap(conn, question, application_id=None, ts=None):
    """Record a screening question the answer file couldn't cover (deduped)."""
    t = ts or now()
    q = norm(question)
    row = conn.execute(
        "SELECT id FROM answer_gaps WHERE question_norm=?", (q,)
    ).fetchone()
    if row:
        conn.execute(
            "UPDATE answer_gaps SET times_seen=times_seen+1, last_seen=? WHERE id=?",
            (t, row["id"]),
        )
        return row["id"], False
    cur = conn.execute(
        """INSERT INTO answer_gaps
           (created_at, question, question_norm, last_seen, first_application_id)
           VALUES (?,?,?,?,?)""",
        (t, question, q, t, application_id),
    )
    return cur.lastrowid, True
