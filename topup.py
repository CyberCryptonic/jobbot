"""Through-the-day auto-apply top-up (operator 2026-08-31).

The 6 AM discovery + 8 AM submission run once. This runs extra cycles during
the day (scheduled by cron) so hands-off applications keep landing as new
ungated jobs appear, working toward a daily target — WITHOUT ever spending past
the monthly API cap.

What it does NOT do, on purpose:
  - It cannot manufacture supply. The only jobs it can auto-submit are ungated,
    account-free ATS forms (Greenhouse today); most of the market walls
    automation off and routes to the manual queue. Some days the honest number
    is well under the target. It captures what exists; it never pads.
  - It never double-applies. Dedup is enforced upstream: a UNIQUE dedup_key
    (one row per company|title|location), submission only selects `queued`
    rows, and the head refuses any row that already has a submit_click
    ("never twice"). This script relies on those, it does not re-implement them.
  - It never exceeds the monthly cost cap. Paid work (discovery: scoring +
    letters) stops once month-to-date spend reaches the cap minus a headroom;
    the free step (submission: probe + Playwright fill, no API) still runs so
    already-queued jobs keep going out.

Run:  ./venv/bin/python topup.py            # one gated cycle, for cron
      ./venv/bin/python topup.py --dry      # print the decision, run nothing
"""
import json
import subprocess
import sys

import db

CONFIG = json.loads((db.BASE_DIR / "config.json").read_text())
ACFG = CONFIG.get("submission", {}).get("auto_submit", {})
COST = CONFIG.get("cost", {})


def applied_today(conn):
    """Real hands-off sends today: autosubmit_ok rows (a click that confirmed).
    Handoffs and dry runs do not count."""
    return conn.execute(
        "SELECT COUNT(*) c FROM activity_log "
        "WHERE action='autosubmit_ok' AND date(ts)=date('now','localtime')").fetchone()["c"]


def spend_mtd(conn):
    """Month-to-date API dollars. Sum run_end rows only: each run's decision
    rows roll their cost up onto its run_end (db.Run), so summing every row
    counted each dollar twice — the guard tripped at half the real budget
    (found session 12; the dashboard's spend counters use the same run_end
    convention, so the two now agree)."""
    row = conn.execute(
        "SELECT COALESCE(SUM(cost_usd),0) s FROM activity_log "
        "WHERE action='run_end' "
        "AND strftime('%Y-%m', ts)=strftime('%Y-%m','now','localtime')").fetchone()
    return float(row["s"])


def decide(applied_today, spend_mtd, *, daily_target, daily_max, monthly_cap, headroom):
    """Pure policy. Returns {discovery, submission, reason}.

    - at/over the daily max: stop entirely (enough went out today).
    - budget spent to the cap (minus headroom): no paid discovery, but still run
      the free submission step so queued jobs keep applying.
    - target met, budget fine: no need to find more today; apply what's queued.
    - otherwise: a full cycle (find new jobs, then apply).
    """
    if applied_today >= daily_max:
        return {"discovery": False, "submission": False,
                "reason": f"daily max {daily_max} reached ({applied_today} auto-applied); stopping"}
    if spend_mtd >= monthly_cap - headroom:
        return {"discovery": False, "submission": True,
                "reason": f"budget guard: MTD ${spend_mtd:.2f} within ${headroom:.0f} of the "
                          f"${monthly_cap:.0f} cap; applying queued jobs only, no new discovery"}
    if applied_today >= daily_target:
        return {"discovery": False, "submission": True,
                "reason": f"daily target {daily_target} met ({applied_today}); applying any "
                          f"queued jobs, not spending on new discovery"}
    return {"discovery": True, "submission": True,
            "reason": f"{applied_today}/{daily_target} auto-applied, MTD ${spend_mtd:.2f}/"
                      f"${monthly_cap:.0f}: full cycle (find new, then apply)"}


def _run(script):
    """Invoke a pipeline stage as its own process (same as cron), inheriting the
    venv. Returns True on exit 0."""
    p = subprocess.run([str(db.BASE_DIR / "venv/bin/python"), str(db.BASE_DIR / script)],
                       cwd=str(db.BASE_DIR))
    return p.returncode == 0


def main(argv):
    conn = db.connect()
    target = int(ACFG.get("daily_target", 10))
    dmax = int(ACFG.get("daily_max", 10))
    cap = float(COST.get("monthly_cap_usd", 40))
    head = float(COST.get("topup_headroom_usd", 3))
    a, s = applied_today(conn), spend_mtd(conn)
    plan = decide(a, s, daily_target=target, daily_max=dmax, monthly_cap=cap, headroom=head)
    if "--dry" in argv:
        print(json.dumps({"applied_today": a, "spend_mtd": round(s, 2), **plan}, indent=1))
        return
    with db.Run("submission", conn=conn) as run:
        run.log("topup_start", reason=plan["reason"])
        if plan["discovery"]:
            run.log("topup_discovery", reason="running discovery.py (find + score + letters + queue)",
                    outcome="ok" if _run("discovery.py") else "fail")
        if plan["submission"]:
            run.log("topup_submission", reason="running submission.py (auto-apply eligible, walls to manual)",
                    outcome="ok" if _run("submission.py") else "fail")
        after = applied_today(conn)
        run.log("topup_summary",
                reason=f"auto-applied today: {after} (target {target}, max {dmax}); "
                       f"MTD ${spend_mtd(conn):.2f}/${cap:.0f}"
                       + ("" if plan["discovery"] or plan["submission"] else "; idle"))


if __name__ == "__main__":
    if db.halt_if_paused("submission"):
        sys.exit(0)
    main(sys.argv[1:])
