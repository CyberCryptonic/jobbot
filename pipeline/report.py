"""Layer 8 — nightly report (7:00 PM).

One HTML email to REPORT_TO via SMTP, one line to ntfy with the
dashboard link, a copy saved to reports/YYYY-MM-DD.html, plus the two
maintenance jobs db.py reserved for this layer: the CSV export and the
30-day auto-ghost.

Sections, in the order CLAUDE.md lists them: exception queue · applications
sent today · status changes · skipped and why · screening questions the
answer file couldn't cover · postings flagged for embedded text · inbox pass
(classes, action items, follow-ups) · submission packets (dry run or live) ·
letters (with sameness warnings, never suppressed) · source health · warnings
and failures · running totals + week's response rate · token spend today and
MTD · one observation.

Run:  ./venv/bin/python pipeline/report.py            # send
      ./venv/bin/python pipeline/report.py --no-send  # build reports/<date>.html only
      ./venv/bin/python pipeline/report.py --date 2026-08-27
"""

import html
import json
import re
import sys
from pathlib import Path

import db
import mailer
import notify

CONFIG = json.loads((db.BASE_DIR / "config.json").read_text())
RCFG = CONFIG.get("report", {})
DASH = RCFG.get("dashboard_url", "http://localhost")
REPORT_DIR = db.BASE_DIR / "reports"
SHOT_DIR = db.BASE_DIR / "screenshots"

APPLIED_SET = "('applied','screening','interview','offer','rejected','ghosted')"
RESPONDED_SET = "('screening','interview','offer','rejected')"

e = html.escape


# ---------------------------------------------------------------------------
# Data
# ---------------------------------------------------------------------------

def gather(conn, day):
    q = lambda sql, *p: [dict(r) for r in conn.execute(sql, p).fetchall()]
    one = lambda sql, *p: conn.execute(sql, p).fetchone()
    like = day + "%"
    month = day[:7] + "%"
    d = {"day": day}
    d["exceptions"] = q("SELECT id, company, role, exception_type, exception_note, exception_raised_at "
                        "FROM applications WHERE exception_type IS NOT NULL ORDER BY exception_raised_at")
    d["sent"] = q("SELECT id, company, role, tier, salary_posted, fit_score, apply_route, source, notes, date_applied "
                  "FROM applications WHERE date_applied LIKE ? ORDER BY fit_score DESC", like)
    d["status_changes"] = q("SELECT ts, action, subject, application_id, reason FROM activity_log WHERE ts LIKE ? "
                            "AND action IN ('status_change','manual_applied','submit_handoff','auto_ghost',"
                            "'exception_raised','exception_ack','inbox_backfill') ORDER BY id", like)
    d["skipped"] = q("SELECT ts, stage, subject, reason FROM activity_log WHERE ts LIKE ? "
                     "AND action IN ('skip_job','manual_skip','manual_skip_dryrun') ORDER BY id", like)
    d["queue_hold"] = (one("SELECT COUNT(*) c FROM activity_log WHERE ts LIKE ? AND action='queue_hold'", like) or {"c": 0})["c"]
    d["gaps_open"] = q("SELECT question, times_seen, last_seen FROM answer_gaps WHERE status='open' ORDER BY times_seen DESC, last_seen DESC")
    d["gaps_today"] = q("SELECT subject, reason FROM activity_log WHERE ts LIKE ? AND action='answer_gap' ORDER BY id", like)
    d["flagged"] = q("SELECT ts, stage, subject, reason FROM activity_log WHERE ts LIKE ? "
                     "AND action IN ('flag_posting','flag_email','sender_rejected','chat_injection_flag','command_rejected') ORDER BY id", like)
    d["inbox_counts"] = {r["cls"]: r["n"] for r in q(
        "SELECT COALESCE(class_override, class) cls, COUNT(*) n FROM inbox_messages WHERE seen_ts LIKE ? GROUP BY cls", like)}
    d["inbox_items"] = q("SELECT msg_ts, COALESCE(class_override, class) cls, kind, company, role, deadline, summary, "
                         "application_id, applied_at, from_addr FROM inbox_messages WHERE seen_ts LIKE ? "
                         "AND COALESCE(class_override, class) != 'noise' ORDER BY cls, msg_ts", like)
    d["inbox_dry"] = bool(CONFIG.get("inbox_pass", {}).get("dry_run", True))
    d["followups"] = q("SELECT action, subject, reason FROM activity_log WHERE ts LIKE ? "
                       "AND action IN ('followup_sent','followup_drafted','followup_unfollowable') ORDER BY id", like)
    d["sub_dry"] = bool(CONFIG.get("submission", {}).get("dry_run", True))
    d["packets"] = q("SELECT action, outcome, subject, reason FROM activity_log WHERE ts LIKE ? "
                     "AND action IN ('submit_dryrun','submit_handoff','form_record','autosubmit_dryrun','autosubmit_ok',"
                     "'autosubmit_unknown','autosubmit_blocked','autosubmit_gaps','autosubmit_paused','autosubmit_skip',"
                     "'autosubmit_unavailable','submit_click','review_ack') ORDER BY id", like)
    acfg = CONFIG.get("submission", {}).get("auto_submit", {}) or {}
    try:
        ast = json.loads((db.BASE_DIR / "state.json").read_text()).get("auto_submit", {})
    except (OSError, ValueError):
        ast = {}
    d["auto"] = {"enabled": bool(acfg.get("enabled")), "dry_run": bool(acfg.get("dry_run", True)),
                 "live_count": int(ast.get("live_count", 0)), "verify_n": int(acfg.get("verify_first_n", 20)),
                 "awaiting_review": bool(ast.get("awaiting_review")), "platforms": acfg.get("platforms", [])}
    d["inferred"] = q("SELECT subject, reason FROM activity_log WHERE ts LIKE ? AND action='answer_inferred'", like)
    d["letters"] = q("SELECT outcome, subject, reason, cost_usd FROM activity_log WHERE ts LIKE ? "
                     "AND action IN ('letter_written','letter_failed') ORDER BY id", like)
    d["letter_detail_missing"] = (one("SELECT COUNT(*) c FROM activity_log WHERE ts LIKE ? AND action='letter_written' "
                                      "AND token_detail IS NULL", like) or {"c": 0})["c"]
    d["sources"] = [dict(r) for r in db.source_health(conn)]
    d["warns"] = q("SELECT ts, stage, action, outcome, subject, reason FROM activity_log WHERE ts LIKE ? "
                   "AND outcome IN ('warn','fail') AND action NOT IN ('answer_gap','letter_written','followup_drafted',"
                   "'followup_unfollowable','skip_job','manual_skip_dryrun','classify_email','action_needed','inbox_backfill','match_ambiguous') ORDER BY id", like)
    d["runs"] = q("SELECT run_id, stage, ts, outcome, duration_ms, tokens_used, cost_usd, reason FROM activity_log "
                  "WHERE ts LIKE ? AND action='run_end' AND stage != 'chat' ORDER BY id", like)   # chat spend is in spend_by_stage
    d["funnel"] = {r["status"]: r["n"] for r in q("SELECT status, COUNT(*) n FROM applications GROUP BY status")}
    wk = one(f"SELECT COUNT(*) a, SUM(CASE WHEN status IN {RESPONDED_SET} THEN 1 ELSE 0 END) r "
             "FROM applications WHERE date_applied >= ?", db.days_ago(7))
    d["week"] = {"applied": wk["a"] or 0, "responded": wk["r"] or 0}
    d["totals"] = {
        "applied": (one(f"SELECT COUNT(*) c FROM applications WHERE status IN {APPLIED_SET}") or {"c": 0})["c"],
        "active": (one("SELECT COUNT(*) c FROM applications WHERE status IN ('applied','screening','interview')") or {"c": 0})["c"],
        "interviews": (one("SELECT COUNT(*) c FROM applications WHERE status IN ('interview','offer')") or {"c": 0})["c"],
        "queued": (one("SELECT COUNT(*) c FROM applications WHERE status='queued'") or {"c": 0})["c"],
        "manual_queue": len(db.manual_queue(conn)),
    }
    sp = lambda pat: one("SELECT COALESCE(SUM(cost_usd),0) c, COALESCE(SUM(tokens_used),0) t FROM activity_log "
                         "WHERE ts LIKE ? AND action='run_end'", pat)
    st, sm = sp(like), sp(month)
    d["spend"] = {"today_usd": st["c"], "today_tokens": st["t"], "mtd_usd": sm["c"], "mtd_tokens": sm["t"], "cap": 25.0}
    d["spend_by_stage"] = q("SELECT stage, ROUND(SUM(cost_usd),4) c, SUM(tokens_used) t FROM activity_log "
                            "WHERE ts LIKE ? AND action='run_end' GROUP BY stage ORDER BY c DESC", like)
    d["by_source"] = q(f"SELECT source, COUNT(*) a, SUM(CASE WHEN status IN {RESPONDED_SET} THEN 1 ELSE 0 END) r, "
                       "SUM(CASE WHEN status IN ('interview','offer') THEN 1 ELSE 0 END) i "
                       f"FROM applications WHERE status IN {APPLIED_SET} GROUP BY source ORDER BY a DESC")
    d["rejection_days"] = q("SELECT CAST(julianday(last_update) - julianday(date_applied) AS INTEGER) days "
                            "FROM applications WHERE status='rejected' AND date_applied IS NOT NULL")
    d["ghosted_today"] = (one("SELECT COUNT(*) c FROM activity_log WHERE ts LIKE ? AND action='auto_ghost'", like) or {"c": 0})["c"]
    return d


def observation(d):
    """One sentence about what is working, from the numbers only."""
    src = [s for s in d["by_source"] if s["a"] >= 3]
    if src and any(s["r"] for s in src):
        best = max(src, key=lambda s: (s["r"] / s["a"], s["a"]))
        return (f"{best['source']} has the best response rate so far: {best['r']} of {best['a']} applications "
                f"heard back ({best['i']} reached interview).")
    if d["week"]["applied"]:
        return (f"{d['week']['applied']} applications went out in the last 7 days and {d['week']['responded']} have a "
                f"response; most replies in this corpus arrive as rejections within "
                f"{int(sorted(x['days'] for x in d['rejection_days'])[len(d['rejection_days']) // 2]) if d['rejection_days'] else '?'} days.")
    if d["rejection_days"]:
        days = sorted(x["days"] for x in d["rejection_days"])
        return (f"Rejections in the tracker land a median {days[len(days) // 2]} days after applying; "
                f"a row quiet past that is more likely ghosted than pending.")
    if d["sent"]:
        return f"{len(d['sent'])} applications today; no responses yet to compare sources on."
    return "Nothing sent and nothing answered today; the queue holds " + str(d["totals"]["queued"]) + " scored jobs."


# ---------------------------------------------------------------------------
# HTML
# ---------------------------------------------------------------------------

CSS = """
body{font-family:-apple-system,Segoe UI,Helvetica,Arial,sans-serif;font-size:14px;color:#1b1b1b;background:#fff;margin:0;padding:16px}
h1{font-size:18px;margin:0 0 2px}h2{font-size:14px;margin:18px 0 6px;text-transform:uppercase;letter-spacing:.4px;color:#444;border-bottom:1px solid #ddd;padding-bottom:3px}
table{border-collapse:collapse;width:100%;font-size:13px}td,th{text-align:left;padding:4px 6px;border-bottom:1px solid #eee;vertical-align:top}
th{font-weight:600;color:#555;font-size:12px}.n{font-family:Menlo,Consolas,monospace;text-align:right;white-space:nowrap}
.m{font-family:Menlo,Consolas,monospace}.mu{color:#777}.w{color:#9a6a00}.f{color:#b00020}.ok{color:#0a7a2a}
.box{background:#f5f5f4;padding:8px 10px;border-radius:4px;margin:6px 0}
.exc{background:#fff3e0;border-left:4px solid #e0771a;padding:8px 10px;margin:6px 0}
.tiles td{border:none;padding:2px 14px 2px 0}.tiles b{font-size:18px;font-family:Menlo,Consolas,monospace}
"""


def table(headers, rows, cls=""):
    if not rows:
        return '<div class="mu">none</div>'
    h = "".join(f"<th>{e(x)}</th>" for x in headers)
    b = "".join("<tr>" + "".join(f"<td{' class=\"n\"' if isinstance(c, (int, float)) else ''}>{c if isinstance(c, Raw) else e(str(c))}</td>"
                                 for c in r) + "</tr>" for r in rows)
    return f'<table class="{cls}"><tr>{h}</tr>{b}</table>'


class Raw(str):
    """A cell that is already HTML."""


def render(d):
    day = d["day"]
    parts = [f"<style>{CSS}</style>",
             f'<h1>jobbot — {e(day)}</h1><div class="mu"><a href="{e(DASH)}">{e(DASH)}</a> · '
             + ("submission DRY RUN · " if d["sub_dry"] else "")
             + ("inbox DRY RUN" if d["inbox_dry"] else "inbox live") + "</div>"]

    # 1. exception queue
    parts.append("<h2>Exception queue</h2>")
    if d["exceptions"]:
        names = {"interview": "INTERVIEW", "assessment": "ASSESSMENT", "video_interview": "VIDEO INTERVIEW",
                 "signature": "SIGNATURE"}
        for x in d["exceptions"]:
            parts.append(f'<div class="exc"><b>{names.get(x["exception_type"], x["exception_type"])}</b> · '
                         f'{e(x["company"])} — {e(x["role"])}<br>{e(x["exception_note"] or "")} '
                         f'<span class="mu">(raised {e(x["exception_raised_at"])})</span></div>')
    else:
        parts.append('<div class="ok">clear</div>')

    # 2. sent today
    parts.append(f"<h2>Applications sent today ({len(d['sent'])})</h2>")
    parts.append(table(["Company", "Role", "Tier", "Salary", "Score", "Route", "Summary"],
                       [(s["company"], s["role"], s["tier"] or "—", s["salary_posted"] or "—", s["fit_score"] or 0,
                         s["apply_route"] or "—", (s["notes"] or "").split("\n")[0][:160]) for s in d["sent"]]))

    # 3. status changes
    parts.append(f"<h2>Status changes ({len(d['status_changes'])})</h2>")
    parts.append(table(["When", "What", "Job", "Detail"],
                       [(r["ts"][11:16], r["action"], r["subject"] or "", r["reason"] or "") for r in d["status_changes"]]))

    # 4. skipped
    parts.append(f"<h2>Skipped ({len(d['skipped'])}"
                 + (f", {d['queue_hold']} held under the manual-queue cap" if d["queue_hold"] else "") + ")</h2>")
    parts.append(table(["Stage", "Job", "Why"], [(r["stage"], r["subject"] or "", r["reason"] or "") for r in d["skipped"]]))

    # 5. answer gaps
    parts.append(f"<h2>Screening questions the answer file couldn't cover ({len(d['gaps_open'])} open)</h2>")
    parts.append(table(["Question", "Seen", "Last"], [(g["question"][:200], g["times_seen"], g["last_seen"][:10]) for g in d["gaps_open"]]))
    if d["gaps_today"]:
        parts.append(f'<div class="mu">{len(d["gaps_today"])} gap hits today</div>')

    # 6. flagged
    parts.append(f"<h2>Flagged for embedded text or failed verification ({len(d['flagged'])})</h2>")
    parts.append(table(["Stage", "Subject", "Why"], [(r["stage"], r["subject"] or "", r["reason"] or "") for r in d["flagged"]]))

    # 7. inbox
    ic = d["inbox_counts"]
    parts.append("<h2>Inbox pass" + (" (DRY RUN — tracker untouched)" if d["inbox_dry"] else "") + "</h2>")
    parts.append('<div class="box">' + " · ".join(f"{k.replace('_', ' ')} <b>{ic.get(k, 0)}</b>" for k in
                                                 ("confirmation", "rejection", "interview", "offer", "action_needed", "noise")) + "</div>")
    parts.append(table(["Class", "Company — role", "Deadline", "Summary", "Tracker"],
                       [(Raw(f'<span class="{ {"rejection": "f", "interview": "ok", "offer": "ok", "action_needed": "w"}.get(r["cls"], "") }">{e(r["cls"])}{"/" + e(r["kind"]) if r["kind"] else ""}</span>'),
                         f"{r['company'] or r['from_addr']} — {r['role'] or '?'}", r["deadline"] or "", r["summary"] or "",
                         f"#{r['application_id']}" + ("" if r["applied_at"] else " (not applied)") if r["application_id"] else "no row")
                        for r in d["inbox_items"]]))
    if d["followups"]:
        parts.append("<h3>Follow-ups</h3>" + table(["Action", "Job", "Detail"], [(r["action"], r["subject"] or "", r["reason"] or "") for r in d["followups"]]))

    # 8. submission packets
    parts.append("<h2>Submission packets" + (" (DRY RUN — nothing submitted)" if d["sub_dry"] else "") + f" ({len(d['packets'])})</h2>")
    a = d.get("auto") or {}
    if a.get("enabled"):
        parts.append(f'<div class="mu">auto-submit head: {"DRY RUN (fills and screenshots, never clicks)" if a["dry_run"] else "LIVE"} · '
                     f'platforms {", ".join(a["platforms"])} · live sends {a["live_count"]}/{a["verify_n"]}'
                     + (' · <b>self-stopped: review the screenshots, then run submission.py --reviewed</b>' if a["awaiting_review"] else '')
                     + '</div>')
    else:
        parts.append('<div class="mu">auto-submit head: off (every packet is a handoff)</div>')
    parts.append(table(["Action", "Job", "Detail"], [(r["action"], r["subject"] or "", (r["reason"] or "")[:220]) for r in d["packets"]]))
    if d["inferred"]:
        parts.append(f'<div class="mu">{len(d["inferred"])} answers inferred under §L rule 2 (see Agent view: answer_inferred)</div>')

    # 9. letters — sameness warnings surfaced, never suppressed
    warned = [l for l in d["letters"] if l["outcome"] in ("warn", "fail")]
    parts.append(f"<h2>Letters ({len(d['letters'])} written, {len(warned)} with warnings)</h2>")
    parts.append(table(["Outcome", "Job", "Detail"], [(l["outcome"], l["subject"] or "", (l["reason"] or "")[:260]) for l in warned]))
    if d["letter_detail_missing"]:
        parts.append(f'<div class="mu">letter cost note: {d["letter_detail_missing"]} letter rows today carry total tokens '
                     f'but no cache-read split (known gap from session 3); the dollar figures below are exact, the cache hit rate for letters is not visible.</div>')

    # 10. sources
    parts.append("<h2>Source health (last run vs previous)</h2>")
    parts.append(table(["Source", "Found", "Previous", "Outcome", "Last run"],
                       [(s["source"], s["found"] if s["found"] is not None else "—", s["prev"] if s["prev"] is not None else "—",
                         Raw(f'<span class="{"w" if s["outcome"] == "warn" else "f" if s["outcome"] == "fail" else ""}">{e(s["outcome"])}</span>'),
                         s["last_ts"]) for s in d["sources"]]))

    # 11. warnings / failures
    parts.append(f"<h2>Warnings and failures ({len(d['warns'])})</h2>")
    parts.append(table(["When", "Stage", "Action", "Outcome", "Subject", "Why"],
                       [(r["ts"][11:16], r["stage"], r["action"], Raw(f'<span class="{"f" if r["outcome"] == "fail" else "w"}">{e(r["outcome"])}</span>'),
                         r["subject"] or "", (r["reason"] or "")[:240]) for r in d["warns"]]))

    # 12. totals
    t, w, f = d["totals"], d["week"], d["funnel"]
    rate = f"{100 * w['responded'] / w['applied']:.0f}%" if w["applied"] else "—"
    parts.append("<h2>Running totals</h2>")
    parts.append('<table class="tiles"><tr>'
                 + "".join(f"<td><b>{v}</b><br><span class=\"mu\">{k}</span></td>" for k, v in
                           (("applied (all time)", t["applied"]), ("active", t["active"]), ("interviews", t["interviews"]),
                            ("rejected", f.get("rejected", 0)), ("ghosted", f.get("ghosted", 0)),
                            ("queued", t["queued"]), ("manual queue", t["manual_queue"]),
                            ("week applied", w["applied"]), ("week responded", f"{w['responded']} ({rate})")))
                 + "</tr></table>")
    if d["ghosted_today"]:
        parts.append(f'<div class="mu">{d["ghosted_today"]} rows auto-ghosted today (30 days without movement)</div>')

    # 13. spend
    s = d["spend"]
    parts.append("<h2>Token spend</h2>")
    parts.append(f'<div class="box">today <b class="m">${s["today_usd"]:.4f}</b> ({s["today_tokens"]:,} tokens) · '
                 f'month to date <b class="m">${s["mtd_usd"]:.2f}</b> of ${s["cap"]:.0f} ({100 * s["mtd_usd"] / s["cap"]:.0f}%) · {s["mtd_tokens"]:,} tokens</div>')
    parts.append(table(["Stage", "Today $", "Tokens"], [(r["stage"], f"{r['c']:.4f}", r["t"] or 0) for r in d["spend_by_stage"]]))
    parts.append(table(["Run", "Outcome", "Duration", "Tokens", "$"],
                       [(r["run_id"], Raw(f'<span class="{"f" if r["outcome"] == "fail" else ""}">{e(r["outcome"])}</span>'),
                         f"{(r['duration_ms'] or 0) / 1000:.0f}s", r["tokens_used"] or 0, f"{r['cost_usd']:.4f}") for r in d["runs"]]))

    # 14. observation
    parts.append("<h2>One observation</h2>")
    parts.append(f'<div class="box">{e(observation(d))}</div>')
    return "\n".join(parts)


def text_summary(d):
    t, w, ic = d["totals"], d["week"], d["inbox_counts"]
    bits = [f"sent {len(d['sent'])}", f"interviews {t['interviews']}", f"exceptions {len(d['exceptions'])}",
            f"rejections {ic.get('rejection', 0)}", f"action {ic.get('action_needed', 0)}",
            f"warn/fail {len(d['warns'])}", f"${d['spend']['today_usd']:.2f} today / ${d['spend']['mtd_usd']:.2f} MTD"]
    return " · ".join(bits)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def attachments_for(day_dir, max_n):
    """PDF form records first (small, the verification artefacts), then only
    the head's confirmation PNGs. Filled/blocked PNGs (~0.7 MB each) are
    linked from the dashboard, never attached (review finding #2)."""
    if not day_dir.exists():
        return []
    return (sorted(day_dir.glob("*.pdf")) + sorted(day_dir.glob("*-confirmed.png")))[:max_n]


def prune_screenshots(shot_dir, keep_days=30, today=None):
    """Delete screenshots/<YYYY-MM-DD>/ older than keep_days. Returns the
    directory names removed. Anything not named like a day is left alone."""
    import shutil
    from datetime import date, timedelta
    today = date.fromisoformat(today or db.today())
    cutoff = today - timedelta(days=int(keep_days))
    removed = []
    if not shot_dir.exists():
        return removed
    for d in sorted(shot_dir.iterdir()):
        if not d.is_dir() or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", d.name):
            continue
        try:
            when = date.fromisoformat(d.name)
        except ValueError:
            continue
        if when < cutoff:
            shutil.rmtree(d)
            removed.append(d.name)
    return removed


def main(argv):
    if db.halt_if_paused("report"):
        return
    day = argv[argv.index("--date") + 1] if "--date" in argv else db.today()
    send = "--no-send" not in argv
    conn = db.connect()
    with db.Run("report", conn=conn) as run:
        if day == db.today():
            n = db.ghost_stale(conn, run_id=run.run_id, days=30)
            if n:
                run.log("auto_ghost_pass", reason=f"{n} rows ghosted")
            try:
                path = db.export_csv()
                run.log("csv_export", reason=str(Path(path).relative_to(db.BASE_DIR)))
            except OSError as ex:
                run.log("csv_export", outcome="fail", reason=str(ex)[:200])
        keep = int(RCFG.get("screenshot_retention_days", 30) or 0)
        if keep:
            gone = prune_screenshots(SHOT_DIR, keep_days=keep)
            if gone:
                run.log("screenshots_pruned", reason=f"removed {len(gone)} day folder(s) older than {keep} days: {', '.join(gone)}"[:300])
        d = gather(conn, day)
        body = render(d)
        REPORT_DIR.mkdir(exist_ok=True)
        out = REPORT_DIR / f"{day}.html"
        out.write_text(body)
        summary = text_summary(d)
        attachments = []
        if RCFG.get("attach_form_records", True):
            attachments = attachments_for(SHOT_DIR / day, int(RCFG.get("max_attachments", 20)))
        if not send:
            run.log("report_built", reason=f"{out.name} built, not sent ({summary})")
            print(f"built {out} — {summary}")
            return
        subject = f"jobbot {day}: {len(d['sent'])} sent · {t_int(d['totals']['interviews'])} interviews · {len(d['exceptions'])} exceptions"
        try:
            skipped = mailer.send(db.ENV["REPORT_TO"], subject, summary + f"\n\nOpen the HTML version.\n{DASH}", html=body,
                                  attachments=attachments)
            run.log("report_sent", reason=f"{out.name} → REPORT_TO, {len(attachments) - len(skipped)} attachments"
                    + (f", {len(skipped)} left out for size" if skipped else ""))
        except Exception as ex:
            run.log("report_sent", outcome="fail", reason=f"SMTP failed: {type(ex).__name__}: {ex}"[:300])
            notify.push("jobbot report FAILED to send", f"{type(ex).__name__}: {str(ex)[:120]}\n{DASH}", priority=4, tags=["warning"])
            raise
        ok = notify.push(f"jobbot {day}", summary, priority=3, tags=["clipboard"], click=DASH)
        run.log("ntfy_push", outcome="ok" if ok else "fail", reason="nightly one-liner" if ok else "ntfy push failed")
        print(f"sent {out.name} — {summary}")
    conn.close()


def t_int(x):
    return int(x or 0)


if __name__ == "__main__":
    main(sys.argv[1:])
