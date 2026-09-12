"""Operator rules added 2026-08-29 (session 9):
 1. at most one queue slot per company per title per day — the highest-scored
    instance queues, the rest stay 'discovered' and are logged;
 2. internship-titled postings are Tier C."""
import pytest

import db
import scoring
from conftest import add_job


# --- rule 2: internships are Tier C -----------------------------------------

@pytest.mark.parametrize("title", [
    "Information Security Engineer, Internship",
    "Security Analyst Intern",
    "SOC Analyst Intern (Summer 2027)",
    "Cybersecurity Co-op",
    "Cyber Security Interns - Rotational Program",
])
def test_internship_titles_are_tier_c(title):
    assert scoring.tier_for(title, "A") == "C"


@pytest.mark.parametrize("title,expected", [
    ("International Security Analyst", "A"),     # 'intern' inside a word is not an internship
    ("Internal Audit Security Analyst", "A"),
    ("Security Operations Analyst", "A"),
    ("Network Engineer", "B"),
])
def test_non_internship_titles_keep_their_tier(title, expected):
    assert scoring.tier_for(title, None) == expected


# --- rule 1: one per company per title per day --------------------------------

def _queued_ids(conn):
    return [r["id"] for r in conn.execute(
        "SELECT id FROM applications WHERE status='queued' ORDER BY id")]


def test_one_slot_per_company_title_keeps_highest_score(scratch_db, monkeypatch):
    conn = scratch_db
    monkeypatch.setitem(scoring.CONFIG["quota"], "daily_max", 10)
    a = add_job(conn, "Meridian Dynamics", "Security Operations Analyst", location="Boston, MA", score=82, tier="A")
    b = add_job(conn, "Meridian Dynamics", "Security Operations Analyst", location="Washington, DC", score=85, tier="A")
    c = add_job(conn, "Meridian Dynamics", "Security Operations Analyst", location="Seattle, WA", score=80, tier="A")
    d = add_job(conn, "Meridian Dynamics", "Security Operations Analyst", location="Costa Mesa, CA", score=78, tier="A")
    other = add_job(conn, "Meridian Dynamics", "Detection Engineer", location="Boston, MA", score=75, tier="B")
    with db.Run("scoring", conn=conn) as run:
        n = scoring.queue_build(run, conn)
    assert _queued_ids(conn) == sorted([b, other])
    assert n == 2
    for jid in (a, c, d):
        row = conn.execute("SELECT status FROM applications WHERE id=?", (jid,)).fetchone()
        assert row["status"] == "discovered"          # not skipped: eligible another day
    log = conn.execute("SELECT application_id, outcome, reason FROM activity_log WHERE action='queue_dedupe' ORDER BY id").fetchall()
    assert {r["application_id"] for r in log} == {a, c, d}
    assert all(r["outcome"] == "skip" for r in log)
    assert f"#{b}" in log[0]["reason"]


def test_dedupe_does_not_consume_quota(scratch_db, monkeypatch):
    conn = scratch_db
    monkeypatch.setitem(scoring.CONFIG["quota"], "daily_max", 2)
    add_job(conn, "Meridian Dynamics", "Security Operations Analyst", location="Boston, MA", score=85, tier="A")
    add_job(conn, "Meridian Dynamics", "Security Operations Analyst", location="Seattle, WA", score=84, tier="A")
    add_job(conn, "Meridian Dynamics", "Security Operations Analyst", location="Costa Mesa, CA", score=83, tier="A")
    e = add_job(conn, "Graphite Analytics", "Defensive Security Analyst", location="New York, NY", score=70, tier="A")
    with db.Run("scoring", conn=conn) as run:
        scoring.queue_build(run, conn)
    assert e in _queued_ids(conn)
    assert len(_queued_ids(conn)) == 2


def test_already_queued_instance_blocks_a_new_one(scratch_db, monkeypatch):
    conn = scratch_db
    monkeypatch.setitem(scoring.CONFIG["quota"], "daily_max", 10)
    old = add_job(conn, "Meridian Dynamics", "Security Operations Analyst", location="Boston, MA", score=78, tier="A", status="queued")
    new = add_job(conn, "Meridian Dynamics", "Security Operations Analyst", location="Seattle, WA", score=90, tier="A")
    with db.Run("scoring", conn=conn) as run:
        scoring.queue_build(run, conn)
    assert _queued_ids(conn) == [old]
    assert conn.execute("SELECT status FROM applications WHERE id=?", (new,)).fetchone()["status"] == "discovered"


def test_rule_off_restores_old_behaviour(scratch_db, monkeypatch):
    conn = scratch_db
    monkeypatch.setitem(scoring.CONFIG["quota"], "daily_max", 10)
    monkeypatch.setitem(scoring.CONFIG["quota"], "one_per_company_title", False)
    add_job(conn, "Meridian Dynamics", "Security Operations Analyst", location="Boston, MA", score=82, tier="A")
    add_job(conn, "Meridian Dynamics", "Security Operations Analyst", location="Seattle, WA", score=80, tier="A")
    with db.Run("scoring", conn=conn) as run:
        scoring.queue_build(run, conn)
    assert len(_queued_ids(conn)) == 2
