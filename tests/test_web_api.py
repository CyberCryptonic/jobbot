"""Web API tests — the dashboard backend (web.py).

Covers the session-12 dashboard revamp surface: extended /api/shell
notifications, /api/stats chart data, the answer-bank manager
(/api/answers*), on-demand cover letters (/api/application/<id>/letter*),
and /api/agents, plus regression checks that every pre-existing endpoint
still answers 200 against a scratch database.

Every test runs on scratch_db (conftest) — never jobbot.db. Answer-bank
tests point answers.PATH at a throwaway copy; letter tests patch
letters.generate_one so no API call is made.
"""

import json
import shutil
from datetime import datetime
from pathlib import Path

import pytest

import answers
import db
import web
from tests.conftest import add_job

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture
def client(scratch_db, monkeypatch, tmp_path):
    # keep answer-bank writes and backups away from the real files
    bank = tmp_path / "answers.md"
    shutil.copyfile(ROOT / "config" / "application-answers.example.md", bank)
    monkeypatch.setattr(answers, "PATH", bank)
    monkeypatch.setattr(web, "BACKUP_DIR", tmp_path / "backups")
    web.app.config["TESTING"] = True
    with web.app.test_client() as c:
        yield c


# ---------------------------------------------------------------------------
# answers.update_row (unit)
# ---------------------------------------------------------------------------

def test_update_row_edits_in_place(tmp_path):
    bank = tmp_path / "a.md"
    shutil.copyfile(ROOT / "config" / "application-answers.example.md", bank)
    line = answers.update_row("A", "Target base salary", "$95,000", path=bank)
    assert isinstance(line, int)
    loaded = answers.load(bank)
    assert loaded["A"]["Target base salary"] == "$95,000"
    # other rows untouched
    assert loaded["A"]["Minimum base salary"] == "$50,000"


def test_update_row_missing_field_raises(tmp_path):
    bank = tmp_path / "a.md"
    shutil.copyfile(ROOT / "config" / "application-answers.example.md", bank)
    with pytest.raises(KeyError):
        answers.update_row("A", "No such field", "x", path=bank)


def test_update_row_field_cell_kept_verbatim(tmp_path):
    bank = tmp_path / "a.md"
    shutil.copyfile(ROOT / "config" / "application-answers.example.md", bank)
    answers.update_row("D", "Years of professional IT experience", "4", path=bank)
    assert "| Years of professional IT experience | 4 |" in bank.read_text()
    assert answers.load(bank)["D"]["Years of professional IT experience"] == "4"


# ---------------------------------------------------------------------------
# /api/shell — notifications + next runs
# ---------------------------------------------------------------------------

def test_shell_clear_state_has_no_notifications(client, scratch_db, monkeypatch):
    monkeypatch.setattr(web, "_auto_state", lambda: ({}, {}))  # head state is env-dependent
    d = client.get("/api/shell").get_json()
    assert d["notifications"] == []
    assert isinstance(d["next_runs"], list) and d["next_runs"]
    assert {"stage", "at", "label"} <= set(d["next_runs"][0])
    assert "auto" in d and "spend" in d


def test_shell_exception_notification_targets_application(client, scratch_db):
    jid = add_job(scratch_db, "Acme", "SOC Analyst", score=80, tier="A",
                  status="applied")
    db.raise_exception(scratch_db, jid, "interview", "reply by Friday",
                       run_id="t-run", stage="inbox")
    d = client.get("/api/shell").get_json()
    kinds = [n["kind"] for n in d["notifications"]]
    assert "exception" in kinds
    n = next(x for x in d["notifications"] if x["kind"] == "exception")
    assert n["target"] == f"/applications#app-{jid}"
    assert n["app_id"] == jid
    assert "Acme" in n["title"]


def test_shell_gap_notification(client, scratch_db):
    db.upsert_answer_gap(scratch_db, "Shirt size?")
    d = client.get("/api/shell").get_json()
    n = next(x for x in d["notifications"] if x["kind"] == "gaps")
    assert n["target"] == "/answers#gaps"
    assert n["count"] == 1


def test_next_runs_parses_crontab():
    runs = web._next_runs(now=datetime(2026, 8, 31, 7, 30, tzinfo=db.TZ))
    stages = [r["stage"] for r in runs]
    assert "submission" in stages and "discovery" in stages
    sub = next(r for r in runs if r["stage"] == "submission")
    assert sub["at"].startswith("2026-08-31 08:00")
    disc = next(r for r in runs if r["stage"] == "discovery")
    assert disc["at"].startswith("2026-09-01 06:00")  # 6 AM already past


# ---------------------------------------------------------------------------
# /api/stats
# ---------------------------------------------------------------------------

def test_stats_shapes(client, scratch_db):
    jid = add_job(scratch_db, "Acme", "SOC Analyst", score=80, tier="A",
                  source="linkedin", status="applied")
    scratch_db.execute("UPDATE applications SET date_applied=? WHERE id=?",
                       (db.now(), jid))
    d = client.get("/api/stats?days=14").get_json()
    assert len(d["days"]) == 14
    assert {"d", "discovered", "applied", "spend"} <= set(d["days"][0])
    assert d["days"][-1]["applied"] == 1        # newest day last
    src = next(s for s in d["sources"] if s["source"] == "linkedin")
    assert src["label"] == "LinkedIn" and src["applied"] == 1
    assert d["cost"]["cap"] > 0
    assert isinstance(d["funnel"], list)
    assert isinstance(d["by_stage_mtd"], list)


# ---------------------------------------------------------------------------
# /api/answers — read + edit + append + gaps
# ---------------------------------------------------------------------------

def test_answers_get_sections_and_flags(client):
    d = client.get("/api/answers").get_json()
    keys = [s["key"] for s in d["sections"]]
    assert "A" in keys and "M" in keys and "ID" in keys
    a = next(s for s in d["sections"] if s["key"] == "A")
    assert a["editable"] and a["attest"]
    assert any(r["field"] == "Minimum base salary" for r in a["rows"])
    l = next(s for s in d["sections"] if s["key"] == "L")
    assert not l["editable"] and l["prose"]
    assert "gaps" in d
    assert d["identity"]["fields"]["first_name"]


def test_answers_edit_row_backs_up_and_logs(client, scratch_db):
    r = client.post("/api/answers/row", json={
        "section": "A", "field": "Target base salary", "answer": "$92,000",
        "original_field": "Target base salary"})
    assert r.status_code == 200 and r.get_json()["ok"]
    assert answers.load()["A"]["Target base salary"] == "$92,000"
    backups = list(web.BACKUP_DIR.glob("application-answers.*.md"))
    assert len(backups) == 1
    row = scratch_db.execute(
        "SELECT * FROM activity_log WHERE action='answer_bank_update'").fetchone()
    assert row and "Target base salary" in row["subject"]


def test_answers_edit_missing_row_404(client):
    r = client.post("/api/answers/row", json={
        "section": "A", "field": "Nope", "answer": "x", "original_field": "Nope"})
    assert r.status_code == 404


def test_answers_append_row(client, scratch_db):
    r = client.post("/api/answers/row", json={
        "section": "E", "field": "Willing to wear a hat", "answer": "Yes"})
    assert r.status_code == 200
    assert answers.load()["E"]["Willing to wear a hat"] == "Yes"


def test_answers_rejects_empty(client):
    r = client.post("/api/answers/row", json={"section": "E", "field": "", "answer": ""})
    assert r.status_code == 400


def test_gap_answer_closes_and_writes_bank(client, scratch_db):
    gid, _ = db.upsert_answer_gap(scratch_db, "What is your shirt size?")
    r = client.post(f"/api/answers/gaps/{gid}", json={"answer": "Large"})
    assert r.status_code == 200
    g = scratch_db.execute("SELECT * FROM answer_gaps WHERE id=?", (gid,)).fetchone()
    assert g["status"] == "answered" and g["answer"] == "Large"
    assert answers.load()["M"]["What is your shirt size?"] == "Large"


def test_gap_dismiss(client, scratch_db):
    gid, _ = db.upsert_answer_gap(scratch_db, "Favorite color?")
    r = client.post(f"/api/answers/gaps/{gid}", json={"dismiss": True})
    assert r.status_code == 200
    g = scratch_db.execute("SELECT * FROM answer_gaps WHERE id=?", (gid,)).fetchone()
    assert g["status"] == "dismissed"


def test_gap_answer_unknown_404(client):
    assert client.post("/api/answers/gaps/9999", json={"answer": "x"}).status_code == 404


# ---------------------------------------------------------------------------
# Cover letters on demand
# ---------------------------------------------------------------------------

CANNED_BODY = (
    "At Lakeview I led three teammates building the Cyber Range, separate Red "
    "Team, Target, and SOC zones behind three OPNsense firewalls. The build "
    "taught me how alerts actually reach an analyst.\n\n"
    "Acme's posting asks for SIEM work. I deployed Security Onion 2.4 and "
    "the Elastic Stack on that range, enrolled agents through Fleet, and "
    "forwarded firewall telemetry until dashboards showed real traffic.\n\n"
    "A conversation about the role would be welcome.")


def _canned_result(*a, **k):
    return dict(body=CANNED_BODY, hooks=[1, 2], angle="range to SOC", why="Real SIEM reps.",
                attempts=1, hard=[], soft=[], sim=0.0, sim_with=None,
                usage={"tokens_used": 10, "cost_usd": 0.0001, "token_detail": None},
                dur=5, drafts=[])


@pytest.fixture
def letters_sandbox(monkeypatch, tmp_path):
    import letters
    monkeypatch.setattr(letters, "generate_one", _canned_result)
    monkeypatch.setattr(letters, "LETTERS_DIR", tmp_path / "letters")
    monkeypatch.setattr(db, "BASE_DIR", tmp_path)   # rel-path anchor for cover_letter_path
    return tmp_path


def test_letter_generate_download_cycle(client, scratch_db, letters_sandbox):
    jid = add_job(scratch_db, "Acme", "SOC Analyst", score=80, tier="A",
                  route="native", status="queued")
    r = client.post(f"/api/application/{jid}/letter", json={})
    assert r.status_code == 200, r.get_json()
    d = r.get_json()
    assert d["ok"] and not d["existing"]
    assert d["url"] == f"/api/application/{jid}/letter.pdf"
    row = scratch_db.execute("SELECT cover_letter_path FROM applications WHERE id=?",
                             (jid,)).fetchone()
    assert row["cover_letter_path"]

    pdf = client.get(d["url"])
    assert pdf.status_code == 200
    assert pdf.headers["Content-Type"] == "application/pdf"
    assert "attachment" in pdf.headers.get("Content-Disposition", "")
    assert pdf.data[:5] == b"%PDF-"

    # second POST reuses the letter instead of regenerating
    r2 = client.post(f"/api/application/{jid}/letter", json={})
    assert r2.get_json()["existing"] is True


def test_letter_refused_for_suspicious(client, scratch_db, letters_sandbox):
    jid = add_job(scratch_db, "Evil Co", "Analyst", score=70, status="queued")
    scratch_db.execute("UPDATE applications SET suspicious=1 WHERE id=?", (jid,))
    assert client.post(f"/api/application/{jid}/letter", json={}).status_code == 409


def test_letter_pdf_404_when_absent(client, scratch_db):
    jid = add_job(scratch_db, "Acme", "SOC Analyst", status="queued")
    assert client.get(f"/api/application/{jid}/letter.pdf").status_code == 404
    assert client.post("/api/application/9999/letter", json={}).status_code == 404


# ---------------------------------------------------------------------------
# /api/agents
# ---------------------------------------------------------------------------

def test_agents_shape(client, scratch_db):
    with db.Run("discovery", conn=scratch_db):
        pass
    d = client.get("/api/agents").get_json()
    stages = {a["stage"]: a for a in d["agents"]}
    assert "discovery" in stages and "inbox" in stages
    disc = stages["discovery"]
    assert disc["purpose"] and disc["last"]["outcome"] == "ok"
    assert "next_at" in disc and "spend" in disc
    assert "head" in d and "live_count" in d["head"]
    assert d["totals"]["cap"] > 0


# ---------------------------------------------------------------------------
# Regression: pre-existing endpoints still answer
# ---------------------------------------------------------------------------

def test_existing_endpoints_still_200(client, scratch_db):
    add_job(scratch_db, "Acme", "SOC Analyst", score=80, tier="A",
            route="native", status="queued")
    for url in ("/api/health", "/api/overview", "/api/queue", "/api/submissions",
                "/api/inbox", "/api/applications", "/api/activity", "/api/runs",
                "/api/chat?after=0", "/api/shell", "/api/stats", "/api/answers",
                "/api/agents"):
        assert client.get(url).status_code == 200, url


def test_pages_serve(client):
    for path in ("/", "/queue", "/applications", "/agent", "/submissions",
                 "/inbox", "/chat", "/answers"):
        r = client.get(path)
        assert r.status_code == 200, path
        assert b"<html" in r.data or b"<main" in r.data


def test_overview_cap_reads_config(client, scratch_db):
    d = client.get("/api/overview").get_json()
    cap = json.loads((ROOT / "config.json").read_text())["cost"]["monthly_cap_usd"]
    assert d["spend"]["cap_usd"] == cap


# ---------------------------------------------------------------------------
# Session 13: notification center persistence + agent mesh contract
# ---------------------------------------------------------------------------

def test_notifications_carry_stable_key_and_group(client, scratch_db, monkeypatch):
    monkeypatch.setattr(web, "_auto_state", lambda: ({}, {}))
    jid = add_job(scratch_db, "Acme", "SOC Analyst", score=80, tier="A", status="applied")
    db.raise_exception(scratch_db, jid, "interview", "reply Fri", run_id="t", stage="inbox")
    db.upsert_answer_gap(scratch_db, "Shirt size?")
    d = client.get("/api/shell").get_json()
    exc = next(n for n in d["notifications"] if n["kind"] == "exception")
    assert exc["key"] == f"exc-{jid}" and exc["group"] == "needs_you"
    gaps = next(n for n in d["notifications"] if n["kind"] == "gaps")
    assert gaps["group"] == "needs_you" and gaps["key"].startswith("gaps-")
    assert isinstance(d["seen"], list)


def test_intro_notice_shows_until_marked_seen(client, scratch_db, monkeypatch):
    monkeypatch.setattr(web, "_auto_state", lambda: ({}, {}))
    d = client.get("/api/shell").get_json()
    assert d["intro"] and d["intro"]["key"] == "intro-v1"
    assert d["notifications"] == []          # intro is its own field, not a banner item
    r = client.post("/api/notifs/seen", json={"keys": ["intro-v1"]})
    assert r.status_code == 200 and r.get_json()["ok"]
    d2 = client.get("/api/shell").get_json()
    assert d2["intro"] is None
    assert "intro-v1" in d2["seen"]


def test_notifs_seen_rejects_bad_body(client, scratch_db):
    assert client.post("/api/notifs/seen", json={"keys": "nope"}).status_code == 400
    assert client.post("/api/notifs/seen", json={}).status_code == 400


def test_needs_you_item_persists_after_seen(client, scratch_db, monkeypatch):
    monkeypatch.setattr(web, "_auto_state", lambda: ({}, {}))
    jid = add_job(scratch_db, "Meridian", "Analyst", score=70, status="applied")
    db.raise_exception(scratch_db, jid, "interview", "call", run_id="t", stage="inbox")
    client.post("/api/notifs/seen", json={"keys": [f"exc-{jid}"]})
    d = client.get("/api/shell").get_json()
    assert any(n["key"] == f"exc-{jid}" for n in d["notifications"])   # still listed
    assert f"exc-{jid}" in d["seen"]                                   # badge calms


def test_history_derived_from_activity_log(client, scratch_db, monkeypatch):
    monkeypatch.setattr(web, "_auto_state", lambda: ({}, {}))
    jid = add_job(scratch_db, "Acme", "SOC Analyst", score=80, status="applied")
    db.raise_exception(scratch_db, jid, "interview", "x", run_id="t", stage="inbox")
    db.ack_exception(scratch_db, jid, run_id="t2")
    d = client.get("/api/shell").get_json()
    assert isinstance(d["history"], list) and d["history"]
    h = d["history"][0]
    assert {"ts", "title", "kind"} <= set(h)
    assert any("Acme" in x["title"] for x in d["history"])


# ---------------------------------------------------------------------------
# Session 14: normalized event feed for the 3D scenes (real audit rows only)
# ---------------------------------------------------------------------------

def _seed_events(conn):
    jid = add_job(conn, "Acme", "SOC Analyst", score=80, tier="A", status="queued")
    with db.Run("scoring", conn=conn) as run:
        run.log("score_job", subject="Acme — SOC Analyst", application_id=jid,
                outcome="ok", reason="Tier A, 80")
        run.log("stage_summary", reason="scored 1")            # unmapped → silent
    db.log("discovery", "fetch_source", run_id="r-d", subject="adzuna",
           outcome="ok", detail=json.dumps({"found": 7}), conn=conn)
    db.log("discovery", "fetch_source", run_id="r-d", subject="usajobs",
           outcome="fail", reason="429", conn=conn)
    db.log("inbox", "classify_email", run_id="r-i", subject="a@b | Interview",
           outcome="ok", reason="interview (0.97) Acme", conn=conn)
    return jid


def test_events_normalized_from_activity_log(client, scratch_db):
    jid = _seed_events(scratch_db)
    d = client.get("/api/events").get_json()
    types = [e["type"] for e in d["events"]]
    assert "run_start" in types and "run_end" in types
    assert "job_scored" in types and "job_discovered" in types
    assert "email_classified" in types
    assert "agent_error" in types                       # the failed fetch
    assert "stage_summary" not in types                 # unmapped stays silent
    scored = next(e for e in d["events"] if e["type"] == "job_scored")
    assert scored["application_id"] == jid and scored["stage"] == "scoring"
    disc = next(e for e in d["events"] if e["type"] == "job_discovered")
    assert disc["count"] == 7                            # aggregated, not per-job
    cls = next(e for e in d["events"] if e["type"] == "email_classified")
    assert cls["cls"] == "interview"
    ids = [e["id"] for e in d["events"]]
    assert ids == sorted(ids)                            # ascending for playback


def test_events_filters(client, scratch_db):
    jid = _seed_events(scratch_db)
    d = client.get(f"/api/events?application_id={jid}").get_json()
    assert d["events"] and all(e.get("application_id") == jid for e in d["events"])
    run_id = d["events"][0]["run_id"]
    d2 = client.get(f"/api/events?run_id={run_id}").get_json()
    assert d2["events"] and all(e["run_id"] == run_id for e in d2["events"])
    last = client.get("/api/events").get_json()["events"][-1]["id"]
    d3 = client.get(f"/api/events?since_id={last}").get_json()
    assert d3["events"] == []


def test_shell_completed_group(client, scratch_db, monkeypatch):
    monkeypatch.setattr(web, "_auto_state", lambda: ({}, {}))
    with db.Run("discovery", conn=scratch_db):
        pass
    d = client.get("/api/shell").get_json()
    assert isinstance(d["completed"], list) and d["completed"]
    c = d["completed"][0]
    assert c["stage"] == "discovery" and c["outcome"] == "ok" and "ts" in c


def test_followup_sent_projects_when_emitted(client, scratch_db):
    """inbox.py logs followup_sent when a follow-up really sends (it is
    draft-gated in production today, so no row exists yet). The event feed
    must project it when it happens — and stay silent until then."""
    jid = add_job(scratch_db, "Acme", "SOC Analyst", score=80, status="applied")
    before = client.get("/api/events").get_json()["events"]
    assert not any(e["type"] == "followup_sent" for e in before)
    db.log("inbox", "followup_sent", run_id="r-f", subject="Acme — SOC Analyst",
           application_id=jid, outcome="ok", reason="day-7 follow-up", conn=scratch_db)
    after = client.get("/api/events").get_json()["events"]
    evt = next(e for e in after if e["type"] == "followup_sent")
    assert evt["application_id"] == jid and evt["stage"] == "inbox"


def test_event_stream_shape(client, scratch_db):
    _seed_events(scratch_db)
    r = client.get("/api/events/stream?once=1")
    assert r.status_code == 200
    assert r.headers["Content-Type"].startswith("text/event-stream")
    body = r.get_data(as_text=True)
    assert "retry:" in body and "data:" in body
    line = next(l for l in body.splitlines() if l.startswith("data:"))
    evt = json.loads(line[5:])
    assert "type" in evt and "id" in evt


def test_agents_core_and_materials_backlog(client, scratch_db):
    jid = add_job(scratch_db, "Acme", "SOC Analyst", score=80, tier="A",
                  route="ats", status="queued")
    d = client.get("/api/agents").get_json()
    assert {"state", "daily_target", "spend_mtd", "cap", "queue_count",
            "queue_cap", "applied_today_auto"} <= set(d["core"])
    mats = next(a for a in d["agents"] if a["stage"] == "materials")
    assert mats["backlog"] == 1              # queued, unsuspicious, letterless, not thin-native
