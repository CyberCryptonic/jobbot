"""jobbot dashboard web service.

Serves the static dashboard pages and a JSON API that reads/writes SQLite.
Runs under waitress on 127.0.0.1:8090; Caddy reverse-proxies :80 to it, so
nothing here is reachable except through Caddy (or locally).

Run manually:   ./venv/bin/python pipeline/web.py
Run for real:   systemd unit jobbot-web (systemd/jobbot-web.service)

Design notes:
- Every handler opens its own short-lived SQLite connection (autocommit + WAL),
  so this process never holds locks against the cron jobs or chatd.
- Manual-queue buttons write here directly (instant), NOT through the commands
  table — the 3s chatd poll is for chat only.
- All content from the DB is rendered client-side with textContent/escaping;
  job posting text is untrusted data end to end.
"""

import json
import re
import shutil
from contextlib import closing
from datetime import datetime, timedelta
from pathlib import Path

from flask import Flask, jsonify, request, send_file, send_from_directory

import answers
import db

DASH = db.BASE_DIR / "dashboard"
SHOT_DIR = db.BASE_DIR / "screenshots"
app = Flask(__name__)

APPLIED_SET = "('applied','screening','interview','offer','rejected','ghosted')"
RESPONDED_SET = "('screening','interview','offer','rejected')"


def ui_run_id():
    return f"{datetime.now(db.TZ).strftime('%Y%m%d-%H%M%S')}-ui"


def rows_to_dicts(rows):
    return [dict(r) for r in rows]


@app.after_request
def no_store(resp):
    resp.headers["Cache-Control"] = "no-store"
    return resp


# ---------------------------------------------------------------------------
# Pages
# ---------------------------------------------------------------------------

PAGES = {
    "/": "index.html",
    "/queue": "queue.html",
    "/applications": "applications.html",
    "/agent": "agent.html",
    "/submissions": "submissions.html",
    "/inbox": "inbox.html",
    "/answers": "answers.html",
    "/chat": "chat.html",
}

CONFIG_PATH = db.BASE_DIR / "config.json"


def cfg_section(name):
    try:
        return json.loads(CONFIG_PATH.read_text()).get(name, {})
    except (OSError, ValueError):
        return {}


def submission_cfg():
    return cfg_section("submission")

for path, fname in PAGES.items():
    app.add_url_rule(
        path, endpoint=fname,
        view_func=(lambda f: (lambda: send_from_directory(DASH, f)))(fname))


@app.route("/assets/<path:name>")
def assets(name):
    return send_from_directory(DASH / "assets", name)


# ---------------------------------------------------------------------------
# Shell: exception strip + nav badge, polled by every page
# ---------------------------------------------------------------------------

@app.get("/api/health")
def health():
    return jsonify(ok=True, time=db.now())


CRON_STAGE_LABEL = {"discovery": "Discovery + scoring + letters",
                    "submission": "Submission batch", "topup": "Top-up cycle",
                    "inbox": "Inbox pass", "report": "Nightly report"}
CRON_RX = re.compile(r"^(\d{1,2})\s+(\d{1,2})\s+\*\s+\*\s+\*\s+.*python\s+(?:pipeline/)?(\w+)\.py")


def _next_runs(now=None):
    """Next fire time per deploy/crontab line (plain `M H * * *` entries only)."""
    now = now or datetime.now(db.TZ)
    out = []
    try:
        lines = (db.BASE_DIR / "deploy" / "crontab").read_text().splitlines()
    except OSError:
        return out
    for line in lines:
        m = CRON_RX.match(line.strip())
        if not m:
            continue
        minute, hour, stage = int(m.group(1)), int(m.group(2)), m.group(3)
        at = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if at <= now:
            at += timedelta(days=1)
        out.append({"stage": stage, "at": at.strftime(db.FMT),
                    "label": CRON_STAGE_LABEL.get(stage, stage)})
    return sorted(out, key=lambda r: r["at"])


def _auto_state():
    acfg = submission_cfg().get("auto_submit", {}) or {}
    try:
        ast = json.loads((db.BASE_DIR / "state.json").read_text()).get("auto_submit", {})
    except (OSError, ValueError):
        ast = {}
    return acfg, ast


def _running(conn):
    """run_start rows without a run_end in the last 2 hours = in flight now."""
    since = (datetime.now(db.TZ) - timedelta(hours=2)).strftime(db.FMT)
    return rows_to_dicts(conn.execute(
        "SELECT s.stage, s.run_id, s.ts AS since FROM activity_log s "
        "LEFT JOIN activity_log e ON e.run_id=s.run_id AND e.action='run_end' "
        "WHERE s.action='run_start' AND s.ts >= ? AND e.id IS NULL "
        "AND s.stage NOT IN ('ui','system')", (since,)))


def _spend(conn):
    t = db.today()
    row = lambda pat: conn.execute(
        "SELECT COALESCE(SUM(cost_usd),0) c, COALESCE(SUM(tokens_used),0) tk "
        "FROM activity_log WHERE ts LIKE ? AND action='run_end'", (pat + "%",)).fetchone()
    d, m = row(t), row(t[:7])
    return {"today": round(d["c"], 4), "today_tokens": d["tk"],
            "mtd": round(m["c"], 4), "mtd_tokens": m["tk"],
            "cap": float(cfg_section("cost").get("monthly_cap_usd", 25.0))}


def _notifications(conn):
    """Everything that needs (or may need) the operator, each with a direct
    link to the exact place it gets handled, a stable `key` (read-state
    identity: a genuinely new event mints a new key) and a `group`:
    'needs_you' items stay listed until the condition resolves server-side;
    'system' items are informational. An empty list means all clear — the
    shell then shows NOTHING, never a 'queue clear' banner."""
    out = []
    for e in db.open_exceptions(conn):
        out.append({"kind": "exception", "exception_type": e["exception_type"],
                    "app_id": e["id"], "key": f"exc-{e['id']}", "group": "needs_you",
                    "title": f"{e['company']} — {e['role']}",
                    "detail": e["exception_note"] or "",
                    "ts": e["exception_raised_at"],
                    "target": f"/applications#app-{e['id']}"})
    acfg, ast = _auto_state()
    if acfg.get("enabled") and ast.get("awaiting_review"):
        lc, vn = int(ast.get("live_count", 0)), int(acfg.get("verify_first_n", 20))
        out.append({"kind": "review", "key": f"review-{lc}", "group": "needs_you",
                    "title": f"Auto-submit is holding for your review ({lc}/{vn} live sends)",
                    "detail": "The head screenshots each of its first sends and stops until "
                              "you look them over. Review the screenshots, then run "
                              "`./venv/bin/python pipeline/submission.py --reviewed` to let it continue.",
                    "target": "/submissions#review"})
    gaps = db.open_gaps(conn)
    if gaps:
        n = len(gaps)
        newest = max(g["id"] for g in gaps)
        out.append({"kind": "gaps", "count": n, "key": f"gaps-{newest}",
                    "group": "needs_you",
                    "title": f"{n} screening question{'s' if n > 1 else ''} need your answer",
                    "detail": "A form asked something the answer bank doesn't cover. "
                              "Answer once and it fills automatically from then on.",
                    "target": "/answers#gaps"})
    act = conn.execute(
        "SELECT COUNT(*) c, COALESCE(MAX(id),0) mx FROM inbox_messages "
        "WHERE COALESCE(class_override, class)='action_needed' AND msg_ts >= ?",
        (db.days_ago(7),)).fetchone()
    if act["c"]:
        out.append({"kind": "inbox_action", "count": act["c"],
                    "key": f"inbact-{act['mx']}", "group": "system",
                    "title": f"{act['c']} email{'s' if act['c'] > 1 else ''} classified action-needed this week",
                    "detail": "An employer asked for something. Open the inbox to read and handle them.",
                    "target": "/inbox?class=action_needed"})
    carried = conn.execute(
        "SELECT COUNT(*) c FROM applications WHERE status='queued' "
        "AND apply_route='native' AND carried_over > 0").fetchone()["c"]
    if carried:
        out.append({"kind": "carried", "count": carried,
                    "key": f"carried-{db.today()}", "group": "system",
                    "title": f"{carried} queue card{'s' if carried > 1 else ''} carried over from yesterday",
                    "detail": "These one-tap applies rolled forward untouched. Sixty seconds each.",
                    "target": "/queue"})
    fails = conn.execute(
        "SELECT COUNT(*) c FROM activity_log WHERE ts LIKE ? AND outcome='fail'",
        (db.today() + "%",)).fetchone()["c"]
    if fails:
        out.append({"kind": "fails", "count": fails,
                    "key": f"fails-{db.today()}", "group": "system",
                    "title": f"{fails} failure{'s' if fails > 1 else ''} logged today",
                    "detail": "Something went wrong in a run. The Agents page shows exactly what and why.",
                    "target": f"/agent?outcome=fail&date={db.today()}"})
    return out


# Notification read-state: the drawer's Mark-read / badge calm. Real
# persistence (SQLite), lazily created so pre-migration databases work.
INTRO_KEY = "intro-v1"


def _seen_keys(conn):
    conn.execute("CREATE TABLE IF NOT EXISTS notif_seen ("
                 "key TEXT PRIMARY KEY, seen_at TEXT NOT NULL)")
    return [r["key"] for r in conn.execute("SELECT key FROM notif_seen")]


def _intro(seen):
    if INTRO_KEY in seen:
        return None
    return {"key": INTRO_KEY, "kind": "intro", "group": "system",
            "title": "This is your command center",
            "detail": "JobBot finds jobs, writes letters, applies, and reads the "
                      "replies on its own. Anything that ever needs your hand shows "
                      "up here, under Needs you — everything else is just the record. "
                      "Mark this read and it will not appear again.",
            "target": "/"}


HISTORY_ACTIONS = ("exception_ack", "answer_bank_update", "answer_gap_dismissed",
                   "config_change")


def _history(conn, limit=12):
    """Resolved-notification trail, derived live from the activity log —
    acks, answer-bank changes, config changes. No shadow store."""
    rows = conn.execute(
        f"SELECT ts, action, subject, reason FROM activity_log "
        f"WHERE action IN ({','.join('?' * len(HISTORY_ACTIONS))}) "
        f"ORDER BY id DESC LIMIT ?", (*HISTORY_ACTIONS, limit)).fetchall()
    return [{"ts": r["ts"], "kind": r["action"],
             "title": r["subject"] or (r["reason"] or "")[:80],
             "detail": (r["reason"] or "")[:200]} for r in rows]


@app.post("/api/notifs/seen")
def notifs_seen():
    body = request.get_json(silent=True) or {}
    keys = body.get("keys")
    if not isinstance(keys, list) or not keys or \
            not all(isinstance(k, str) and 0 < len(k) <= 120 for k in keys):
        return jsonify(error="keys must be a non-empty list of strings"), 400
    with closing(db.connect()) as conn:
        _seen_keys(conn)                      # ensure table
        for k in keys:
            conn.execute("INSERT INTO notif_seen (key, seen_at) VALUES (?, ?) "
                         "ON CONFLICT(key) DO UPDATE SET seen_at=excluded.seen_at",
                         (k, db.now()))
    return jsonify(ok=True, count=len(keys))


@app.get("/api/shell")
def shell():
    with closing(db.connect()) as conn:
        exceptions = rows_to_dicts(db.open_exceptions(conn))
        queue_count = len(db.manual_queue(conn))
        notifications = _notifications(conn)
        running = _running(conn)
        spend = _spend(conn)
        gaps_open = len(db.open_gaps(conn))
        seen = _seen_keys(conn)
        history = _history(conn)
        completed = rows_to_dicts(conn.execute(
            "SELECT ts, stage, reason FROM activity_log WHERE action='run_end' "
            "AND outcome='ok' AND stage NOT IN ('ui','system') "
            "ORDER BY id DESC LIMIT 10"))
        for c in completed:
            c["outcome"] = "ok"
    acfg, ast = _auto_state()
    return jsonify(exceptions=exceptions, queue_count=queue_count,
                   dry_run=bool(submission_cfg().get("dry_run", True)),
                   paused=bool(db.pipeline_paused()),
                   notifications=notifications, next_runs=_next_runs()[:6],
                   running=running, spend=spend, gaps_open=gaps_open,
                   seen=seen, history=history, completed=completed, intro=_intro(seen),
                   auto={"enabled": bool(acfg.get("enabled")),
                         "dry_run": bool(acfg.get("dry_run", True)),
                         "live_count": int(ast.get("live_count", 0)),
                         "verify_first_n": int(acfg.get("verify_first_n", 20)),
                         "awaiting_review": bool(ast.get("awaiting_review"))})


@app.post("/api/exceptions/<int:app_id>/ack")
def ack_exception(app_id):
    with closing(db.connect()) as conn:
        db.ack_exception(conn, app_id, run_id=ui_run_id())
    return jsonify(ok=True)


# ---------------------------------------------------------------------------
# Overview
# ---------------------------------------------------------------------------

@app.get("/api/overview")
def overview():
    t = db.today()
    month = t[:7]
    week_ago = db.days_ago(7)
    with closing(db.connect()) as conn:
        one = lambda q, *p: conn.execute(q, p).fetchone()

        today_stats = {
            "discovered": one("SELECT COUNT(*) c FROM applications WHERE first_seen LIKE ?", t + "%")["c"],
            "scored": one("SELECT COUNT(*) c FROM activity_log WHERE action='score_job' AND ts LIKE ?", t + "%")["c"],
            "applied": one("SELECT COUNT(*) c FROM applications WHERE date_applied LIKE ?", t + "%")["c"],
            "skipped": one("SELECT COUNT(*) c FROM activity_log WHERE action='skip_job' AND ts LIKE ?", t + "%")["c"],
        }
        totals = {
            "applied": one(f"SELECT COUNT(*) c FROM applications WHERE status IN {APPLIED_SET}")["c"],
            "active": one("SELECT COUNT(*) c FROM applications WHERE status IN ('applied','screening','interview')")["c"],
            "interviews": one("SELECT COUNT(*) c FROM applications WHERE status IN ('interview','offer')")["c"],
            "rejected": one("SELECT COUNT(*) c FROM applications WHERE status='rejected'")["c"],
            "ghosted": one("SELECT COUNT(*) c FROM applications WHERE status='ghosted'")["c"],
        }
        wk = one(
            f"""SELECT COUNT(*) applied,
                SUM(CASE WHEN status IN {RESPONDED_SET} THEN 1 ELSE 0 END) responded
                FROM applications WHERE date_applied >= ?""", week_ago)
        week = {"applied": wk["applied"] or 0, "responded": wk["responded"] or 0}

        spend_row = lambda pat: one(
            "SELECT COALESCE(SUM(cost_usd),0) c, COALESCE(SUM(tokens_used),0) t "
            "FROM activity_log WHERE ts LIKE ? AND action='run_end'", pat)
        sp_t, sp_m = spend_row(t + "%"), spend_row(month + "%")
        spend = {"today_usd": round(sp_t["c"], 4), "today_tokens": sp_t["t"],
                 "mtd_usd": round(sp_m["c"], 4), "mtd_tokens": sp_m["t"],
                 "cap_usd": float(cfg_section("cost").get("monthly_cap_usd", 25.0))}

        # Last run per stage: latest run_start, matched to its run_end.
        stages = []
        for s in conn.execute(
                "SELECT stage, MAX(ts) mts FROM activity_log "
                "WHERE action='run_start' AND stage NOT IN ('ui','system') "
                "GROUP BY stage ORDER BY stage"):
            start = one("SELECT * FROM activity_log WHERE stage=? AND action='run_start' AND ts=?",
                        s["stage"], s["mts"])
            end = one("SELECT * FROM activity_log WHERE run_id=? AND action='run_end'",
                      start["run_id"])
            stages.append({
                "stage": s["stage"], "start_ts": start["ts"],
                "outcome": end["outcome"] if end else "running",
                "duration_ms": end["duration_ms"] if end else None,
                "reason": (end["reason"] if end else None) or "",
                "tokens": end["tokens_used"] if end else 0,
            })

        sources = db.source_health(conn)
        funnel = rows_to_dicts(conn.execute(
            "SELECT status, COUNT(*) n FROM applications GROUP BY status"))
        recent = rows_to_dicts(conn.execute(
            "SELECT ts, stage, action, subject, outcome, reason "
            "FROM activity_log WHERE action NOT IN ('run_start') "
            "ORDER BY id DESC LIMIT 15"))
    return jsonify(today=today_stats, totals=totals, week=week, spend=spend,
                   stages=stages, sources=sources, funnel=funnel, recent=recent)


# ---------------------------------------------------------------------------
# Manual queue
# ---------------------------------------------------------------------------

@app.get("/api/queue")
def queue():
    with closing(db.connect()) as conn:
        held = conn.execute(
            "SELECT COUNT(*) c FROM applications WHERE status='discovered' "
            "AND fit_score IS NOT NULL AND suspicious=0 "
            "AND (apply_route='native' OR apply_route IS NULL) "
            "AND tier IN ('A','B')").fetchone()["c"]
        cards = []
        for r in db.manual_queue(conn):
            card = dict(r)
            card["screening_answers"] = json.loads(r["screening_answers"] or "[]")
            card["letter_text"] = ""
            if r["cover_letter_path"]:
                # the tracker stores the PDF that ships; the copy button wants
                # the plain-text twin written alongside it
                p = (db.BASE_DIR / r["cover_letter_path"]).with_suffix(".txt")
                try:
                    card["letter_text"] = p.read_text()
                except (OSError, UnicodeDecodeError):
                    card["letter_text"] = ""      # never let one bad file 500 the queue
            card["why"] = (r["notes"] or "").split("\n")[0]
            # thin posting (an alert stub, under 200 chars): the pipeline scored it on
            # the title and wrote no letter; the operator reads the real posting first
            card["thin"] = len((r["job_description"] or "").strip()) < 200
            card["read_first"] = ("Read the posting before applying: the pipeline only saw "
                                  f"{len((r['job_description'] or '').strip())} characters of it.") if card["thin"] else ""
            cards.append(card)
    return jsonify(cards=cards, held=held)


def _queue_action(app_id, new_status, action, reason):
    with closing(db.connect()) as conn:
        row = conn.execute("SELECT * FROM applications WHERE id=?", (app_id,)).fetchone()
        if not row:
            return jsonify(error="no such application"), 404
        if row["status"] != "queued":
            return jsonify(error=f"not in queue (status: {row['status']})"), 409
        if submission_cfg().get("dry_run", True):
            # DRY RUN: log the complete intended action, hide the card, change
            # nothing that could pass for a real submission. Undo with
            # `submission.py --reset-dryrun`.
            conn.execute("UPDATE applications SET next_action=?, last_update=? WHERE id=?",
                         (f"DRY-RUN {new_status} {db.now()}", db.now(), app_id))
            db.log("ui", action + "_dryrun", run_id=ui_run_id(),
                   subject=f"{row['company']} — {row['role']}",
                   application_id=app_id, outcome="ok" if new_status == "applied" else "skip",
                   reason=f"[DRY RUN] would set status={new_status}: {reason}. Row left queued, card hidden.",
                   detail=json.dumps({"would_set_status": new_status, "apply_route": row["apply_route"],
                                      "job_url": row["job_url"], "cover_letter_path": row["cover_letter_path"],
                                      "screening_answers": json.loads(row["screening_answers"] or "[]")}),
                   conn=conn)
            return jsonify(ok=True, dry_run=True)
        db.set_status(conn, app_id, new_status, append_note=reason)
        db.log("ui", action, run_id=ui_run_id(),
               subject=f"{row['company']} — {row['role']}",
               application_id=app_id,
               outcome="ok" if new_status == "applied" else "skip",
               reason=reason, conn=conn)
    return jsonify(ok=True)


# ---------------------------------------------------------------------------
# Submissions — the intended-action log (packets built by submission.py)
# ---------------------------------------------------------------------------

@app.get("/api/submissions")
def submissions():
    with closing(db.connect()) as conn:
        rows = conn.execute(
            "SELECT id, submission_path FROM applications WHERE submission_path IS NOT NULL "
            "ORDER BY fit_score DESC, id").fetchall()
        packets = []
        for r in rows:
            p = db.BASE_DIR / r["submission_path"]
            try:
                packets.append(json.loads(p.read_text()))
            except (OSError, ValueError):
                continue
        native = len(db.manual_queue(conn))
        hidden = conn.execute("SELECT COUNT(*) c FROM applications WHERE next_action LIKE 'DRY-RUN%'").fetchone()["c"]
        ui_dry = rows_to_dicts(conn.execute(
            "SELECT ts, action, subject, application_id, reason FROM activity_log "
            "WHERE action IN ('manual_applied_dryrun','manual_skip_dryrun') ORDER BY id DESC LIMIT 50").fetchall())
        # the autonomous head's latest word on each packet + its screenshots
        for p in packets:
            r = conn.execute("SELECT ts, action, outcome, reason FROM activity_log WHERE application_id=? "
                             "AND action LIKE 'autosubmit_%' ORDER BY id DESC LIMIT 1", (p["application_id"],)).fetchone()
            shots = []
            for day_dir in sorted(SHOT_DIR.glob("20*"), reverse=True)[:14]:
                for f in sorted(day_dir.glob(f"{p['application_id']}-*.png")):
                    shots.append(f"/screenshots/{day_dir.name}/{f.name}")
            p["auto"] = {"ts": r["ts"], "action": r["action"], "outcome": r["outcome"], "reason": r["reason"]} if r else None
            p["screenshots"] = shots
    counts = {}
    for p in packets:
        counts[p["decision"]] = counts.get(p["decision"], 0) + 1
    scfg = submission_cfg()
    acfg = scfg.get("auto_submit", {}) or {}
    try:
        ast = json.loads((db.BASE_DIR / "state.json").read_text()).get("auto_submit", {})
    except (OSError, ValueError):
        ast = {}
    return jsonify(dry_run=bool(scfg.get("dry_run", True)), packets=packets,
                   counts=counts, manual_queue=native, manual_hidden_dryrun=hidden, ui_dryrun=ui_dry,
                   auto_submit={"enabled": bool(acfg.get("enabled")), "dry_run": bool(acfg.get("dry_run", True)),
                                "platforms": acfg.get("platforms", []), "live_count": int(ast.get("live_count", 0)),
                                "verify_first_n": int(acfg.get("verify_first_n", 20)),
                                "awaiting_review": bool(ast.get("awaiting_review"))})


@app.get("/screenshots/<day>/<name>")
def screenshot_file(day, name):
    """Form records and the head's filled/confirmed/blocked screenshots. Only
    png/pdf, only from screenshots/<YYYY-MM-DD>/."""
    if not re.fullmatch(r"20\d\d-\d\d-\d\d", day) or not re.fullmatch(r"[\w.-]+\.(png|pdf)", name):
        return jsonify(error="not found"), 404
    return send_from_directory(SHOT_DIR / day, name)


@app.post("/api/queue/<int:app_id>/applied")
def queue_applied(app_id):
    return _queue_action(app_id, "applied", "manual_applied",
                         "marked applied from manual queue")


@app.post("/api/queue/<int:app_id>/skip")
def queue_skip(app_id):
    body = request.get_json(silent=True) or {}
    reason = body.get("reason") or "skipped from manual queue"
    return _queue_action(app_id, "skipped", "manual_skip", reason)


# ---------------------------------------------------------------------------
# Inbox — Layer 7 classifications, shown and editable
# ---------------------------------------------------------------------------

INBOX_CLASSES = ("confirmation", "rejection", "interview", "offer", "action_needed", "noise")


@app.get("/api/inbox")
def inbox_list():
    days = min(int(request.args.get("days", 45)), 365)
    since = db.days_ago(days)
    with closing(db.connect()) as conn:
        rows = rows_to_dicts(conn.execute(
            "SELECT * FROM inbox_messages WHERE msg_ts >= ? ORDER BY msg_ts DESC, uid DESC LIMIT 1500",
            (since,)))
        last = conn.execute(
            "SELECT ts FROM activity_log WHERE stage='inbox' AND action='run_end' ORDER BY id DESC LIMIT 1"
        ).fetchone()
    counts, overrides = {}, 0
    for r in rows:
        eff = r["class_override"] or r["class"]
        counts[eff] = counts.get(eff, 0) + 1
        overrides += 1 if r["class_override"] else 0
    return jsonify(rows=rows, counts=counts, overrides=overrides,
                   dry_run=bool(cfg_section("inbox_pass").get("dry_run", True)),
                   last_run=last["ts"] if last else None)


@app.post("/api/inbox/<int:msg_id>/class")
def inbox_override(msg_id):
    body = request.get_json(silent=True) or {}
    cls = body.get("cls")
    if cls not in INBOX_CLASSES:
        return jsonify(error="unknown class"), 400
    with closing(db.connect()) as conn:
        row = conn.execute("SELECT * FROM inbox_messages WHERE id=?", (msg_id,)).fetchone()
        if not row:
            return jsonify(error="no such message"), 404
        override = None if cls == row["class"] else cls
        # a corrected row that already reached the tracker is re-applied by the
        # next live pass (applied_at cleared); the log keeps the correction
        conn.execute("UPDATE inbox_messages SET class_override=?, applied_at=NULL WHERE id=?",
                     (override, msg_id))
        db.log("ui", "inbox_override", run_id=ui_run_id(),
               subject=f"{row['from_addr']} | {(row['subject'] or '')[:60]}",
               application_id=row["application_id"], outcome="ok",
               reason=f"operator set class {row['class']} → {cls}" if override else f"operator restored class {cls}",
               conn=conn)
    return jsonify(ok=True, class_override=override)


# ---------------------------------------------------------------------------
# Applications
# ---------------------------------------------------------------------------

APP_COLS = ("id, date_applied, company, role, tier, source, apply_route, "
            "salary_posted, location, fit_score, status, last_update, "
            "next_action, carried_over, suspicious, company_norm, first_seen")


@app.get("/api/applications")
def applications():
    q = "SELECT " + APP_COLS + " FROM applications WHERE 1=1"
    params = []
    for field in ("status", "tier", "apply_route"):
        v = request.args.get(field if field != "apply_route" else "route")
        if v:
            q += f" AND {field}=?"
            params.append(v)
    text = request.args.get("q")
    if text:
        q += " AND (company LIKE ? OR role LIKE ? OR location LIKE ? OR notes LIKE ?)"
        params += [f"%{text}%"] * 4
    q += " ORDER BY COALESCE(date_applied, first_seen) DESC, id DESC LIMIT 500"
    with closing(db.connect()) as conn:
        rows = rows_to_dicts(conn.execute(q, params))
        counts = db.reapply_counts(conn)
    return jsonify(rows=rows, company_counts=counts)


@app.get("/api/application/<int:app_id>")
def application_detail(app_id):
    with closing(db.connect()) as conn:
        row = conn.execute("SELECT * FROM applications WHERE id=?", (app_id,)).fetchone()
        if not row:
            return jsonify(error="no such application"), 404
        history = rows_to_dicts(conn.execute(
            "SELECT ts, stage, action, outcome, reason FROM activity_log "
            "WHERE application_id=? ORDER BY id", (app_id,)))
    d = dict(row)
    d["history"] = history
    return jsonify(d)


# ---------------------------------------------------------------------------
# Agent view
# ---------------------------------------------------------------------------

@app.get("/api/activity")
def activity():
    q = "SELECT * FROM activity_log WHERE 1=1"
    params = []
    for field in ("stage", "outcome", "run_id"):
        v = request.args.get(field)
        if v:
            q += f" AND {field}=?"
            params.append(v)
    date = request.args.get("date")
    if date:
        q += " AND ts LIKE ?"
        params.append(date + "%")
    text = request.args.get("q")
    if text:
        q += " AND (subject LIKE ? OR reason LIKE ? OR detail LIKE ? OR action LIKE ?)"
        params += [f"%{text}%"] * 4
    limit = min(int(request.args.get("limit", 200)), 1000)
    q += f" ORDER BY id DESC LIMIT {limit}"

    t = db.today()
    month = t[:7]
    with closing(db.connect()) as conn:
        rows = rows_to_dicts(conn.execute(q, params))
        one = lambda qq, *p: conn.execute(qq, p).fetchone()
        counters = {
            "rows_today": one("SELECT COUNT(*) c FROM activity_log WHERE ts LIKE ?", t + "%")["c"],
            "fails_today": one("SELECT COUNT(*) c FROM activity_log WHERE ts LIKE ? AND outcome='fail'", t + "%")["c"],
            "flags_today": one("SELECT COUNT(*) c FROM activity_log WHERE ts LIKE ? AND outcome='flag'", t + "%")["c"],
            "tokens_today": one("SELECT COALESCE(SUM(tokens_used),0) c FROM activity_log WHERE ts LIKE ? AND action='run_end'", t + "%")["c"],
            "cost_mtd": round(one("SELECT COALESCE(SUM(cost_usd),0) c FROM activity_log WHERE ts LIKE ? AND action='run_end'", month + "%")["c"], 4),
        }
    return jsonify(rows=rows, counters=counters)


@app.get("/api/runs")
def runs():
    days = min(int(request.args.get("days", 7)), 31)
    since = db.days_ago(days - 1)  # include today
    with closing(db.connect()) as conn:
        starts = conn.execute(
            "SELECT * FROM activity_log WHERE action='run_start' AND ts >= ? "
            "AND stage NOT IN ('ui','system') ORDER BY ts", (since,)).fetchall()
        out = []
        for s in starts:
            e = conn.execute(
                "SELECT * FROM activity_log WHERE run_id=? AND action='run_end'",
                (s["run_id"],)).fetchone()
            out.append({
                "run_id": s["run_id"], "stage": s["stage"],
                "start_ts": s["ts"], "date": s["ts"][:10],
                "outcome": e["outcome"] if e else "running",
                "duration_ms": e["duration_ms"] if e else None,
                "tokens": e["tokens_used"] if e else 0,
                "cost_usd": e["cost_usd"] if e else 0,
                "reason": (e["reason"] if e else None) or "",
            })
    return jsonify(runs=out, days=days)


# ---------------------------------------------------------------------------
# Chat
# ---------------------------------------------------------------------------

@app.get("/api/chat")
def chat_get():
    """Messages after `after`, plus the live state the page pins: pending
    proposals (Confirm/Cancel buttons), unsent drafts (Send button), open
    answer gaps (prompt), and the pause flag."""
    after = int(request.args.get("after", 0))
    with closing(db.connect()) as conn:
        msgs = rows_to_dicts(conn.execute(
            "SELECT id, ts, role, content, command_id, tool_calls FROM chat_messages "
            "WHERE id > ? ORDER BY id LIMIT 200", (after,)))
        busy = conn.execute(
            "SELECT COUNT(*) c FROM commands WHERE status IN ('pending','running')"
        ).fetchone()["c"] > 0
        proposals = db.pending_proposals(conn)
        drafts = rows_to_dicts(conn.execute(
            "SELECT id, created_at, application_id, to_addr, subject, body FROM email_drafts "
            "WHERE status='draft' ORDER BY id DESC LIMIT 10"))
        gaps = db.open_gaps(conn)
    paused = db.pipeline_paused()
    return jsonify(messages=msgs, busy=busy, proposals=proposals, drafts=drafts, gaps=gaps,
                   paused=({"since": paused.get("since"), "reason": paused.get("reason")} if paused else None))


@app.post("/api/chat/reset")
def chat_reset():
    """Start a new conversation: chatd replays history only after this marker."""
    with closing(db.connect()) as conn:
        db.add_chat(conn, "system", f"session reset {db.now()}")
    return jsonify(ok=True)


@app.post("/api/drafts/<int:draft_id>/send")
def draft_send(draft_id):
    """The one place a chat-written email is sent: the operator's click."""
    import mailer
    with closing(db.connect()) as conn:
        d = conn.execute("SELECT * FROM email_drafts WHERE id=?", (draft_id,)).fetchone()
        if not d:
            return jsonify(error="no such draft"), 404
        if d["status"] != "draft":
            return jsonify(error=f"draft is {d['status']}"), 409
        try:
            mailer.send(d["to_addr"], d["subject"], d["body"])
        except Exception as e:
            conn.execute("UPDATE email_drafts SET error=? WHERE id=?", (f"{type(e).__name__}: {e}"[:300], draft_id))
            db.log("ui", "draft_send", run_id=ui_run_id(), subject=d["subject"][:120],
                   application_id=d["application_id"], outcome="fail",
                   reason=f"SMTP failed sending draft #{draft_id} to {d['to_addr']}: {type(e).__name__}", conn=conn)
            return jsonify(error=f"send failed: {type(e).__name__}: {e}"[:200]), 502
        conn.execute("UPDATE email_drafts SET status='sent', sent_at=?, error=NULL WHERE id=?", (db.now(), draft_id))
        if d["application_id"]:
            conn.execute("UPDATE applications SET notes=COALESCE(notes || char(10), '') || ?, last_update=? WHERE id=?",
                         (f"email sent from chat draft #{draft_id} to {d['to_addr']}: {d['subject']}", db.now(), d["application_id"]))
        db.log("ui", "draft_send", run_id=ui_run_id(), subject=d["subject"][:120],
               application_id=d["application_id"], outcome="ok",
               reason=f"operator sent chat draft #{draft_id} to {d['to_addr']}", conn=conn)
        db.add_chat(conn, "system", f"draft #{draft_id} sent to {d['to_addr']}: {d['subject']}")
    return jsonify(ok=True)


@app.post("/api/drafts/<int:draft_id>/discard")
def draft_discard(draft_id):
    with closing(db.connect()) as conn:
        n = conn.execute("UPDATE email_drafts SET status='discarded' WHERE id=? AND status='draft'", (draft_id,)).rowcount
        if n:
            db.add_chat(conn, "system", f"draft #{draft_id} discarded")
    return jsonify(ok=bool(n))


@app.post("/api/chat")
def chat_post():
    body = request.get_json(silent=True) or {}
    text = (body.get("message") or "").strip()
    if not text:
        return jsonify(error="empty message"), 400
    if len(text) > 4000:
        return jsonify(error="message too long"), 400
    with closing(db.connect()) as conn:
        cmd_id = db.add_command(conn, text)
        msg_id = db.add_chat(conn, "user", text, command_id=cmd_id)
    return jsonify(ok=True, command_id=cmd_id, message_id=msg_id)


# ---------------------------------------------------------------------------
# Stats — chart data for the Overview (and anything else that plots)
# ---------------------------------------------------------------------------

SOURCE_LABEL = {
    "company_page": "Company site", "linkedin": "LinkedIn",
    "linkedin_alert": "LinkedIn", "indeed_alert": "Indeed",
    "ziprecruiter_alert": "ZipRecruiter", "glassdoor_alert": "Glassdoor",
    "adzuna": "Adzuna", "usajobs": "USAJobs", "inbox": "Email alerts",
    "jobright_alert": "Jobright", "manual": "Manual", "seed": "Seed",
}

FUNNEL_ORDER = ("discovered", "queued", "applied", "screening", "interview",
                "offer", "rejected", "ghosted", "skipped")


@app.get("/api/stats")
def stats():
    days = min(max(int(request.args.get("days", 30)), 7), 90)
    labels = [(datetime.now(db.TZ) - timedelta(days=i)).strftime("%Y-%m-%d")
              for i in range(days - 1, -1, -1)]
    with closing(db.connect()) as conn:
        grp = lambda q: {r[0]: r[1] for r in conn.execute(q, (labels[0],))}
        disc = grp("SELECT substr(first_seen,1,10) d, COUNT(*) FROM applications "
                   "WHERE first_seen >= ? GROUP BY d")
        appl = grp("SELECT substr(date_applied,1,10) d, COUNT(*) FROM applications "
                   "WHERE date_applied >= ? GROUP BY d")
        spnd = {r[0]: r[1] for r in conn.execute(
            "SELECT substr(ts,1,10) d, SUM(cost_usd) FROM activity_log "
            "WHERE ts >= ? AND action='run_end' GROUP BY d", (labels[0],))}
        day_rows = [{"d": L, "discovered": disc.get(L, 0), "applied": appl.get(L, 0),
                     "spend": round(spnd.get(L, 0) or 0, 4)} for L in labels]

        src_all = {r[0]: r[1] for r in conn.execute(
            "SELECT source, COUNT(*) FROM applications GROUP BY source")}
        src_sent = {r[0]: r[1] for r in conn.execute(
            f"SELECT source, COUNT(*) FROM applications WHERE status IN {APPLIED_SET} "
            "GROUP BY source")}
        sources = sorted(
            [{"source": s, "label": SOURCE_LABEL.get(s, s.replace('_', ' ').title()),
              "discovered": n, "applied": src_sent.get(s, 0)}
             for s, n in src_all.items()],
            key=lambda x: -x["discovered"])

        status = {r[0]: r[1] for r in conn.execute(
            "SELECT status, COUNT(*) FROM applications GROUP BY status")}
        funnel = [{"status": s, "n": status.get(s, 0)} for s in FUNNEL_ORDER
                  if status.get(s)]
        by_stage = rows_to_dicts(conn.execute(
            "SELECT stage, ROUND(SUM(cost_usd),4) cost, SUM(tokens_used) tokens "
            "FROM activity_log WHERE ts LIKE ? AND action='run_end' "
            "GROUP BY stage ORDER BY cost DESC", (db.today()[:7] + "%",)))
        tiers = rows_to_dicts(conn.execute(
            "SELECT tier, COUNT(*) n FROM applications WHERE tier IS NOT NULL "
            "GROUP BY tier ORDER BY tier"))
        routes = rows_to_dicts(conn.execute(
            "SELECT apply_route AS route, COUNT(*) n FROM applications "
            "WHERE apply_route IS NOT NULL GROUP BY apply_route"))
        cost = _spend(conn)
    return jsonify(days=day_rows, sources=sources, funnel=funnel,
                   by_stage_mtd=by_stage, tiers=tiers, routes=routes, cost=cost)


# ---------------------------------------------------------------------------
# Answer bank — read, edit, append, close gaps. The operator's own file,
# edited from the dashboard with a daily backup and a log row per change.
# The chat agent still only appends (its own confirm flow); posting text
# never reaches any of this.
# ---------------------------------------------------------------------------

BACKUP_DIR = db.BASE_DIR / "backups"
ATTEST_SECTIONS = {"A", "D", "F"}          # signed-form attestations: edit only if the truth changes
PROSE_SECTIONS = {"G", "I", "J", "L"}      # rules/reference — read-only in the UI


def _backup_answers():
    """One safety copy per day, taken before the first write of that day."""
    BACKUP_DIR.mkdir(exist_ok=True)
    dst = BACKUP_DIR / f"application-answers.{db.today()}.md"
    if not dst.exists():
        shutil.copyfile(answers.PATH, dst)
    return dst


def _clean_answer(text):
    """Collapse whitespace; blank-line paragraph breaks become <br> (the
    format §M already uses; answers.load() turns them back into newlines)."""
    return "<br>".join(" ".join(x.split())
                       for x in re.split(r"\n\s*\n", str(text or "")) if x.strip())[:8000]


def _parse_sections():
    """The file, split into ordered sections for the Answers page."""
    lines = answers.PATH.read_text().splitlines()
    sec_rx, row_rx = answers._SECTION_RX, answers._ROW_RX
    sections, cur = [], {"key": "ID", "title": "Identity & self-identification",
                         "rows": [], "prose": []}
    for line in lines:
        m = sec_rx.match(line.strip())
        if m:
            sections.append(cur)
            cur = {"key": m.group(1), "title": m.group(2).strip(), "rows": [], "prose": []}
            continue
        r = row_rx.match(line.strip())
        if r and r.group(1).lower() != "field" and not set(r.group(1)) <= set(":- "):
            cur["rows"].append({
                "field": r.group(1).replace("**", "").strip().strip('"'),
                "answer": r.group(2).replace("**", "").strip().replace("<br>", "\n")})
        elif not (r or line.strip().startswith("|")):
            cur["prose"].append(line)
    sections.append(cur)
    for s in sections:
        s["prose"] = "\n".join(s["prose"]).strip("\n-— ").strip()
        s["editable"] = s["key"] not in PROSE_SECTIONS
        s["attest"] = s["key"] in ATTEST_SECTIONS
    return sections


@app.get("/api/answers")
def answers_get():
    sections = _parse_sections()
    with closing(db.connect()) as conn:
        gaps = db.open_gaps(conn)
    ident, ident_file = {}, "identity.json"
    for name in ("identity.json", "config/identity.example.json"):
        try:
            ident = {k: v for k, v in
                     json.loads((db.BASE_DIR / name).read_text()).items()
                     if not k.startswith("_")}
            ident_file = name
            break
        except (OSError, ValueError):
            continue
    try:
        mtime = datetime.fromtimestamp(answers.PATH.stat().st_mtime, db.TZ).strftime(db.FMT)
    except OSError:
        mtime = None
    return jsonify(sections=sections, gaps=gaps,
                   identity={"file": ident_file, "fields": ident},
                   file={"name": answers.PATH.name, "modified": mtime})


@app.post("/api/answers/row")
def answers_row():
    body = request.get_json(silent=True) or {}
    section = str(body.get("section") or "").strip().upper()[:2]
    field = " ".join(str(body.get("field") or "").split())[:600]
    answer = _clean_answer(body.get("answer"))
    original = " ".join(str(body.get("original_field") or "").split())[:600]
    if not field or not answer:
        return jsonify(error="field and answer are both required"), 400
    known = {s["key"] for s in _parse_sections() if s["editable"]}
    if section not in known:
        return jsonify(error=f"section {section or '?'} is not editable"), 400
    before = None
    if original:
        bank = answers.load()
        before = (bank.get(section) or {}).get(original)
    _backup_answers()
    try:
        if original:
            line = answers.update_row(section, original, answer)
            what = f"edited §{section} “{original}”"
        else:
            section, line = answers.append_row(section, field, answer)
            what = f"added §{section} “{field}”"
    except KeyError as e:
        return jsonify(error=str(e).strip("'\"")), 404
    except (ValueError, OSError) as e:
        return jsonify(error=str(e)), 400
    db.log("ui", "answer_bank_update", run_id=ui_run_id(),
           subject=original or field, outcome="ok",
           reason=f"{what} from the dashboard Answers page (line {line})",
           detail=json.dumps({"section": section, "field": original or field,
                              "before": before, "after": answer}))
    return jsonify(ok=True, section=section, field=original or field)


@app.post("/api/answers/gaps/<int:gap_id>")
def answers_gap(gap_id):
    body = request.get_json(silent=True) or {}
    with closing(db.connect()) as conn:
        gap = conn.execute("SELECT * FROM answer_gaps WHERE id=?", (gap_id,)).fetchone()
        if not gap:
            return jsonify(error="no such gap"), 404
        if gap["status"] != "open":
            return jsonify(error=f"gap is already {gap['status']}"), 409
        if body.get("dismiss"):
            conn.execute("UPDATE answer_gaps SET status='dismissed', resolved_at=? WHERE id=?",
                         (db.now(), gap_id))
            db.log("ui", "answer_gap_dismissed", run_id=ui_run_id(),
                   subject=gap["question"][:120], outcome="ok",
                   reason="operator dismissed the gap from the Answers page", conn=conn)
            return jsonify(ok=True, dismissed=True)
        answer = _clean_answer(body.get("answer"))
        if not answer:
            return jsonify(error="answer required"), 400
        _backup_answers()
        section, line = answers.append_row("M", gap["question"][:600], answer)
        conn.execute("UPDATE answer_gaps SET status='answered', answer=?, resolved_at=? "
                     "WHERE id=?", (answer, db.now(), gap_id))
        db.log("ui", "answer_bank_update", run_id=ui_run_id(),
               subject=gap["question"][:120], outcome="ok",
               reason=f"gap #{gap_id} answered from the Answers page → §{section} line {line}",
               detail=json.dumps({"gap_id": gap_id, "answer": answer}), conn=conn)
    return jsonify(ok=True, section=section)


# ---------------------------------------------------------------------------
# Cover letters on demand — the Manual Queue's letter button. Reuses the
# materials stage end to end (same prompts, lint, sameness checks, PDF,
# logging), so an on-demand letter is exactly a pipeline letter.
# ---------------------------------------------------------------------------

def _letter_pdf(row):
    p = db.BASE_DIR / row["cover_letter_path"] if row["cover_letter_path"] else None
    return p if p and p.exists() else None


@app.post("/api/application/<int:app_id>/letter")
def letter_generate(app_id):
    body = request.get_json(silent=True) or {}
    force = bool(body.get("force"))
    with closing(db.connect()) as conn:
        row = conn.execute("SELECT * FROM applications WHERE id=?", (app_id,)).fetchone()
        if not row:
            return jsonify(error="no such application"), 404
        if row["suspicious"]:
            return jsonify(error="posting is flagged suspicious — no letter by policy"), 409
        if _letter_pdf(row) and not force:
            return jsonify(ok=True, existing=True,
                           url=f"/api/application/{app_id}/letter.pdf")
        import letters                       # heavy import (anthropic) on first use only
        with db.Run("materials", conn=conn) as run:
            run.log("letter_requested", subject=f"{row['company']} — {row['role']}",
                    application_id=app_id,
                    reason="operator clicked Write letter on the dashboard")
            written = letters.write_letters(run, conn, [row])
        if not written:
            fail = conn.execute(
                "SELECT reason FROM activity_log WHERE application_id=? "
                "AND action='letter_failed' ORDER BY id DESC LIMIT 1", (app_id,)).fetchone()
            return jsonify(error=(fail["reason"] if fail else
                                  "letter generation failed — see the Agent view")), 502
        res = written[0][1]
    return jsonify(ok=True, existing=False, warnings=res.get("soft") or [],
                   url=f"/api/application/{app_id}/letter.pdf")


@app.get("/api/application/<int:app_id>/letter.pdf")
def letter_pdf(app_id):
    with closing(db.connect()) as conn:
        row = conn.execute("SELECT company, cover_letter_path FROM applications WHERE id=?",
                           (app_id,)).fetchone()
    if not row:
        return jsonify(error="no such application"), 404
    p = _letter_pdf(row)
    if not p:
        return jsonify(error="no letter on file for this job"), 404
    co = re.sub(r"[^A-Za-z0-9]+", "-", row["company"]).strip("-") or "Company"
    return send_file(p, as_attachment=True, mimetype="application/pdf",
                     download_name=f"Cover-Letter-{co}.pdf")


# ---------------------------------------------------------------------------
# Agents — the Agent view's network map: who each agent is, what it just
# did, what it's doing now, what it produces, and what it costs.
# ---------------------------------------------------------------------------

AGENT_META = {
    "discovery": ("Discovery", "Finds new job postings from every source and stores them in the tracker"),
    "scoring": ("Scoring", "Scores each find 0-100 for fit, assigns a tier, and builds the day's queue"),
    "materials": ("Letter writer", "Writes the tailored cover letter and screening answers for each queued job"),
    "submission": ("Submission head", "Fills and submits ATS applications on its own; hands native-route jobs to you"),
    "inbox": ("Inbox reader", "Reads the mailbox, classifies every reply, and updates the tracker"),
    "followup": ("Follow-ups", "Drafts day-7 and day-14 nudges when an employer gave a human reply address"),
    "report": ("Nightly report", "Emails the 7:00 PM digest and pushes the one-line summary to your phone"),
    "chat": ("Chat agent", "Answers your questions and applies the changes you confirm"),
}

AGENT_METRIC = {
    "discovery": ("jobs found", "SELECT COUNT(*) c FROM applications WHERE first_seen LIKE ?"),
    "scoring": ("jobs scored", "SELECT COUNT(*) c FROM activity_log WHERE action='score_job' AND ts LIKE ?"),
    "materials": ("letters written", "SELECT COUNT(*) c FROM activity_log WHERE action='letter_written' AND ts LIKE ?"),
    "submission": ("applications sent", "SELECT COUNT(*) c FROM applications WHERE date_applied LIKE ?"),
    "inbox": ("emails read", "SELECT COUNT(*) c FROM activity_log WHERE action IN ('classify_email','inbox_backfill') AND ts LIKE ?"),
    "followup": ("follow-ups drafted", "SELECT COUNT(*) c FROM activity_log WHERE action='followup_drafted' AND ts LIKE ?"),
    "report": ("reports sent", "SELECT COUNT(*) c FROM activity_log WHERE action='report_sent' AND ts LIKE ?"),
    "chat": ("replies", "SELECT COUNT(*) c FROM activity_log WHERE action='chat_reply' AND ts LIKE ?"),
}

AGENT_CRON = {"discovery": ("discovery",), "scoring": ("discovery",),
              "materials": ("discovery",), "submission": ("submission", "topup"),
              "inbox": ("inbox",), "followup": ("inbox",), "report": ("report",)}


@app.get("/api/agents")
def agents():
    t = db.today()
    month = t[:7]
    nxt = _next_runs()
    with closing(db.connect()) as conn:
        one = lambda q, *p: conn.execute(q, p).fetchone()
        running = {r["stage"]: r for r in _running(conn)}
        out = []
        for stage, (name, purpose) in AGENT_META.items():
            start = one("SELECT * FROM activity_log WHERE stage=? AND action='run_start' "
                        "ORDER BY id DESC LIMIT 1", stage)
            last = None
            if start:
                end = one("SELECT * FROM activity_log WHERE run_id=? AND action='run_end'",
                          start["run_id"])
                last = {"ts": start["ts"],
                        "outcome": end["outcome"] if end else "running",
                        "duration_ms": end["duration_ms"] if end else None,
                        "tokens": end["tokens_used"] if end else 0,
                        "cost": end["cost_usd"] if end else 0,
                        "reason": (end["reason"] if end else None) or ""}
            label, metric_q = AGENT_METRIC[stage]
            spend_q = ("SELECT COALESCE(SUM(cost_usd),0) c, COALESCE(SUM(tokens_used),0) tk "
                       "FROM activity_log WHERE stage=? AND action='run_end' AND ts LIKE ?")
            sp_t = one(spend_q, stage, t + "%")
            sp_m = one(spend_q, stage, month + "%")
            next_at = None
            for cron_stage in AGENT_CRON.get(stage, ()):
                for r in nxt:
                    if r["stage"] == cron_stage:
                        next_at = r["at"] if next_at is None else min(next_at, r["at"])
                        break
            backlog = None
            if stage == "materials":
                # letters still owed: queued, unflagged, letterless, and not a
                # thin native stub (mirrors letters.py THIN_NATIVE_SQL — kept
                # inline so this endpoint never imports the anthropic client)
                backlog = one(
                    "SELECT COUNT(*) c FROM applications WHERE status='queued' "
                    "AND suspicious=0 AND cover_letter_path IS NULL AND NOT "
                    "(apply_route='native' AND LENGTH(COALESCE(job_description,'')) < 200)"
                )["c"]
            out.append({
                "stage": stage, "name": name, "purpose": purpose, "backlog": backlog,
                "last": last, "running": (running.get(stage) or {}).get("run_id"),
                "today": {
                    "decisions": one("SELECT COUNT(*) c FROM activity_log WHERE stage=? "
                                     "AND ts LIKE ? AND action NOT IN ('run_start','run_end')",
                                     stage, t + "%")["c"],
                    "fails": one("SELECT COUNT(*) c FROM activity_log WHERE stage=? "
                                 "AND ts LIKE ? AND outcome='fail'", stage, t + "%")["c"],
                    "metric_label": label,
                    "metric": one(metric_q, t + "%")["c"],
                },
                "spend": {"today": round(sp_t["c"], 4), "today_tokens": sp_t["tk"],
                          "mtd": round(sp_m["c"], 4)},
                "next_at": next_at,
                "always_on": stage == "chat",
            })
        acfg, ast = _auto_state()
        head = {"enabled": bool(acfg.get("enabled")),
                "dry_run": bool(acfg.get("dry_run", True)),
                "live_count": int(ast.get("live_count", 0)),
                "verify_first_n": int(acfg.get("verify_first_n", 20)),
                "awaiting_review": bool(ast.get("awaiting_review")),
                "human_verify_gates": ast.get("human_verify_gates") or [],
                "daily_target": int(acfg.get("daily_target", 0)),
                "last_live": ast.get("last_live"),
                "clicks_today": one("SELECT COUNT(*) c FROM activity_log "
                                    "WHERE action='submit_click' AND ts LIKE ?", t + "%")["c"]}
        spend = _spend(conn)
        totals = {"tokens_today": spend["today_tokens"], "cost_today": spend["today"],
                  "cost_mtd": spend["mtd"], "cap": spend["cap"],
                  "applications": one("SELECT COUNT(*) c FROM applications")["c"],
                  "log_rows": one("SELECT COUNT(*) c FROM activity_log")["c"]}
        queue_count = len(db.manual_queue(conn))
        gaps_open = len(db.open_gaps(conn))
        # the Core instrument: three real gauges + the system state word
        if db.kill_switch() or db.pipeline_paused():
            state = "PAUSED"
        elif submission_cfg().get("dry_run", True):
            state = "DRY RUN"
        elif head["enabled"] and head["awaiting_review"]:
            state = "REVIEW HOLD"
        else:
            state = "AUTONOMOUS"
        core = {"state": state,
                "applied_today_auto": head["clicks_today"],
                "daily_target": head["daily_target"],
                "spend_mtd": spend["mtd"], "spend_today": spend["today"],
                "cap": spend["cap"], "queue_count": queue_count,
                "queue_cap": int(cfg_section("quota").get("manual_queue_cap", 15))}
    return jsonify(agents=out, head=head, totals=totals, core=core,
                   queue_count=queue_count, gaps_open=gaps_open)


# ---------------------------------------------------------------------------
# Normalized event feed — drives the 3D scenes. Read-only projection of
# activity_log per docs/3D_EVENT_MODEL.md: real audit rows in, one event
# vocabulary out; an unmapped action emits nothing. Failures always surface:
# any row with outcome 'fail' becomes agent_error; unmapped warn/flag rows
# become agent_warning.
# ---------------------------------------------------------------------------

EVENT_MAP = {
    "run_start": "run_start", "run_end": "run_end",
    "fetch_source": "job_discovered",
    "score_job": "job_scored", "queue_job": "job_queued",
    "letter_requested": "letter_started", "letter_written": "letter_completed",
    "form_record": "submission_prepared",
    "autosubmit_blocked": "submission_waiting_review",
    "autosubmit_unknown": "submission_waiting_review",
    "submit_click": "submission_sent", "manual_applied": "submission_sent",
    "submit_handoff": "submission_handoff",
    "autosubmit_skip": "submission_skipped", "skip_job": "submission_skipped",
    "manual_skip": "submission_skipped",
    "classify_email": "email_classified",
    "followup_drafted": "followup_scheduled", "followup_sent": "followup_sent",
    "report_sent": "report_generated",
}
INBOX_CLS_RX = re.compile(
    r"^(confirmation|rejection|interview|offer|action_needed|noise)\b")


def _normalize_event(row):
    """activity_log row → normalized event dict, or None (silent)."""
    action, outcome = row["action"], row["outcome"]
    if row["stage"] in ("ui", "system") and action not in ("manual_applied", "manual_skip"):
        mapped = None
    else:
        mapped = EVENT_MAP.get(action)
    if outcome == "fail":
        etype = "agent_error"
    elif mapped:
        etype = mapped
    elif outcome in ("warn", "flag"):
        etype = "agent_warning"
    else:
        return None
    if etype == "email_classified" and INBOX_CLS_RX.match(row["reason"] or ""):
        pass
    evt = {"id": row["id"], "ts": row["ts"], "type": etype, "stage": row["stage"],
           "outcome": outcome, "run_id": row["run_id"],
           "application_id": row["application_id"],
           "subject": (row["subject"] or "")[:120],
           "reason": (row["reason"] or "")[:160]}
    if action == "exception_raised":
        evt["type"] = ("interview_detected"
                       if "interview" in (row["reason"] or "")[:24] else "action_required")
    if action == "action_needed":
        evt["type"] = "action_required"
    if etype == "job_discovered":
        try:
            evt["count"] = int(json.loads(row["detail"] or "{}").get("found") or 0)
        except (ValueError, TypeError):
            evt["count"] = 0
    if etype == "email_classified":
        m = INBOX_CLS_RX.match(row["reason"] or "")
        evt["cls"] = m.group(1) if m else None
    return evt


EVENTFUL_EXTRA = ("exception_raised", "action_needed")


def _event_rows(conn, since_id=0, limit=200, run_id=None, application_id=None,
                stage=None):
    q = ("SELECT id, ts, run_id, stage, action, subject, application_id, outcome, "
         "reason, detail FROM activity_log WHERE id > ?")
    params = [since_id]
    for col, val in (("run_id", run_id), ("application_id", application_id),
                     ("stage", stage)):
        if val:
            q += f" AND {col}=?"
            params.append(val)
    q += " ORDER BY id LIMIT ?"
    params.append(limit)
    out = []
    for row in conn.execute(q, params):
        evt = _normalize_event(row)
        if evt:
            out.append(evt)
    return out


@app.get("/api/events")
def events():
    since_id = int(request.args.get("since_id", 0))
    limit = min(max(int(request.args.get("limit", 200)), 1), 500)
    with closing(db.connect()) as conn:
        out = _event_rows(conn, since_id, limit,
                          run_id=request.args.get("run_id"),
                          application_id=request.args.get("application_id"),
                          stage=request.args.get("stage"))
        last = conn.execute("SELECT COALESCE(MAX(id),0) m FROM activity_log").fetchone()["m"]
    return jsonify(events=out, last_id=last)


@app.get("/api/events/stream")
def events_stream():
    """One-way live event stream (SSE). Each connection self-terminates after
    ~55 s (EventSource auto-reconnects via retry:), so no waitress thread is
    held forever. ?once=1 emits the pending backlog and closes (tests, and
    the polling fallback's first fill)."""
    import time as _time
    # EventSource reconnects (we end each connection ~55s) carry the last
    # delivered id in the Last-Event-ID header — honor it or events replay.
    try:
        since = int(request.headers.get("Last-Event-ID",
                                        request.args.get("since_id", 0)))
    except ValueError:
        since = 0
    once = request.args.get("once") == "1"

    def gen(since_id):
        yield "retry: 3000\n\n"
        deadline = _time.monotonic() + 55
        beat = 0
        while True:
            if beat % 2 == 0:                 # DB poll every other heartbeat
                with closing(db.connect()) as conn:
                    if since_id == 0 and not once:
                        since_id = conn.execute(
                            "SELECT COALESCE(MAX(id),0) m FROM activity_log").fetchone()["m"]
                    batch = _event_rows(conn, since_id, 100)
                for evt in batch:
                    since_id = max(since_id, evt["id"])
                    yield f"id: {evt['id']}\ndata: {json.dumps(evt)}\n\n"
            if once:
                return
            if _time.monotonic() > deadline:
                yield ": bye\n\n"
                return
            # short heartbeat: a dead client raises on this write fast, so a
            # navigated-away page frees its waitress thread within ~1.2s
            yield ": hb\n\n"
            _time.sleep(1.2)
            beat += 1

    from flask import Response
    return Response(gen(since), mimetype="text/event-stream",
                    headers={"Cache-Control": "no-store",
                             "X-Accel-Buffering": "no"})


if __name__ == "__main__":
    from waitress import serve
    print("jobbot web on http://127.0.0.1:8090")
    # threads: each open dashboard tab holds one SSE stream (~1 thread);
    # 16 keeps page loads instant even with several tabs + a stream backlog
    serve(app, host="127.0.0.1", port=8090, threads=16)
