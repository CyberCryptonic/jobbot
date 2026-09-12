"""topup.decide — the gate for the through-the-day auto-apply loop (operator
2026-08-31). Pure policy: how many more cycles to run given the day's progress
and the month's spend. It captures available supply; it cannot manufacture jobs
and it never spends past the cap."""
import topup
from conftest import add_job
import db


def _d(applied, spend, *, target=20, dmax=35, cap=25.0, head=3.0):
    return topup.decide(applied_today=applied, spend_mtd=spend,
                        daily_target=target, daily_max=dmax, monthly_cap=cap, headroom=head)


def test_full_cycle_when_under_target_and_under_budget():
    p = _d(applied=5, spend=10.0)
    assert p["discovery"] and p["submission"]


def test_daily_max_reached_stops_everything():
    p = _d(applied=35, spend=10.0)
    assert not p["discovery"] and not p["submission"] and "max" in p["reason"].lower()


def test_target_met_keeps_applying_queued_but_finds_no_new():
    p = _d(applied=22, spend=10.0)     # >= target 20, < max 35
    assert not p["discovery"] and p["submission"] and "target" in p["reason"].lower()


def test_budget_guard_stops_paid_discovery_but_still_applies_queued_free():
    p = _d(applied=5, spend=23.0)      # 23 >= 25 - 3 headroom
    assert not p["discovery"] and p["submission"] and "budget" in p["reason"].lower()


def test_hard_cap_never_exceeded_even_below_target():
    p = _d(applied=0, spend=25.0)
    assert not p["discovery"]          # spending is frozen at the cap
    assert p["submission"]             # applying already-queued jobs is free


def test_applied_today_counts_only_real_sends_today(scratch_db):
    jid = add_job(scratch_db, "FakeCo", "SOC", status="applied")
    db.log("submission", "autosubmit_ok", run_id="t", application_id=jid, conn=scratch_db)
    db.log("submission", "autosubmit_ok", run_id="t2", application_id=jid, conn=scratch_db)
    db.log("submission", "submit_handoff", run_id="t3", application_id=jid, conn=scratch_db)  # not a real send
    assert topup.applied_today(scratch_db) == 2


def test_spend_mtd_counts_each_dollar_once(scratch_db):
    """Decision rows roll up onto run_end; summing both double-counted the
    budget (session-12 fix). One run logging $0.10 must read as $0.10."""
    import db
    import topup
    with db.Run("scoring", conn=scratch_db) as run:
        run.log("score_job", subject="x", cost_usd=0.10, tokens_used=100)
    assert round(topup.spend_mtd(scratch_db), 6) == 0.10
