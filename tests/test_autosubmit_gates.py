"""autosubmit.eligible — every gate that sends a READY packet back to today's
handoff path (plan §2). No browser, no network."""
import pytest

import db
import autosubmit as A
from conftest import add_job


def _cfg(**over):
    c = {"enabled": True, "dry_run": True, "platforms": ["greenhouse"], "tiers": ["A", "B"],
         "verify_first_n": 20, "max_live_per_run": 3}
    c.update(over)
    return c


def _packet(**over):
    p = {"application_id": 1, "platform": "greenhouse", "decision": "ready", "captcha": False}
    p.update(over)
    return p


@pytest.fixture
def row(scratch_db):
    jid = add_job(scratch_db, "Meridian Dynamics", "Security Operations Analyst", location="Boston, MA",
                  score=82, tier="A", status="queued", url="https://boards.greenhouse.io/meridian/jobs/1")
    return scratch_db.execute("SELECT * FROM applications WHERE id=?", (jid,)).fetchone()


def test_passes_when_everything_holds(scratch_db, row):
    ok, gate, _ = A.eligible(row, _packet(application_id=row["id"]), cfg=_cfg(), state={}, conn=scratch_db, live=False)
    assert ok and gate is None


@pytest.mark.parametrize("over,gate", [
    ({"enabled": False}, "enabled"),
    ({"platforms": ["lever"]}, "platform"),
    ({"tiers": ["A"]}, None),          # tier A still passes
])
def test_config_gates(scratch_db, row, over, gate):
    ok, g, _ = A.eligible(row, _packet(application_id=row["id"]), cfg=_cfg(**over), state={}, conn=scratch_db, live=False)
    assert (g == gate) and (ok == (gate is None))


def test_decision_and_captcha_gates(scratch_db, row):
    assert A.eligible(row, _packet(application_id=row["id"], decision="handoff"), cfg=_cfg(), state={}, conn=scratch_db, live=False)[1] == "decision"
    assert A.eligible(row, _packet(application_id=row["id"], captcha=True), cfg=_cfg(), state={}, conn=scratch_db, live=False)[1] == "captcha"


def test_tier_c_and_suspicious_rows_are_refused(scratch_db, row):
    scratch_db.execute("UPDATE applications SET tier='C' WHERE id=?", (row["id"],))
    r = scratch_db.execute("SELECT * FROM applications WHERE id=?", (row["id"],)).fetchone()
    assert A.eligible(r, _packet(application_id=r["id"]), cfg=_cfg(), state={}, conn=scratch_db, live=False)[1] == "tier"
    scratch_db.execute("UPDATE applications SET tier='A', suspicious=1 WHERE id=?", (row["id"],))
    r = scratch_db.execute("SELECT * FROM applications WHERE id=?", (row["id"],)).fetchone()
    assert A.eligible(r, _packet(application_id=r["id"]), cfg=_cfg(), state={}, conn=scratch_db, live=False)[1] == "suspicious"


def test_reapply_cap_is_rechecked_at_submit_time(scratch_db, row):
    for i in range(3):
        add_job(scratch_db, "Meridian Dynamics", f"Role {i}", location="X", score=70, tier="A", status="applied")
    assert A.eligible(row, _packet(application_id=row["id"]), cfg=_cfg(), state={}, conn=scratch_db, live=False)[1] == "reapply"


def test_prior_submit_click_blocks_forever(scratch_db, row):
    db.log("submission", "submit_click", run_id="t", application_id=row["id"], conn=scratch_db)
    ok, gate, _ = A.eligible(row, _packet(application_id=row["id"]), cfg=_cfg(), state={}, conn=scratch_db, live=False)
    assert gate == "submit_click" and not ok


def test_live_only_gates(scratch_db, row):
    p = _packet(application_id=row["id"])
    # awaiting review stops live sends, not dry runs
    st = {"auto_submit": {"live_count": 2, "awaiting_review": True}}
    assert A.eligible(row, p, cfg=_cfg(), state=st, conn=scratch_db, live=False)[0]
    assert A.eligible(row, p, cfg=_cfg(), state=st, conn=scratch_db, live=True)[1] == "awaiting_review"
    # per-run live cap inside the verification window
    st = {"auto_submit": {"live_count": 5, "awaiting_review": False, "live_this_run": 3}}
    assert A.eligible(row, p, cfg=_cfg(), state=st, conn=scratch_db, live=True)[1] == "max_live_per_run"
    st = {"auto_submit": {"live_count": 25, "awaiting_review": False, "live_this_run": 3}}
    assert A.eligible(row, p, cfg=_cfg(), state=st, conn=scratch_db, live=True)[0]     # unattended after #20


def test_may_submit_reads_pause_file_and_chat_flag(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "PAUSE_FILE", tmp_path / "PAUSE")
    monkeypatch.setattr(db, "pipeline_paused", lambda: None)
    assert A.may_submit()
    (tmp_path / "PAUSE").touch()
    assert not A.may_submit()
    (tmp_path / "PAUSE").unlink()
    monkeypatch.setattr(db, "pipeline_paused", lambda: {"paused": True, "reason": "chat"})
    assert not A.may_submit()


def test_chat_cannot_change_the_head_gates(monkeypatch, tmp_path):
    import json as _j
    import chat_tools as T
    cfg = {"submission": {"auto_submit": {"enabled": False, "dry_run": True, "platforms": ["greenhouse"]}, "max_per_run": 10}}
    (tmp_path / "config.json").write_text(_j.dumps(cfg))
    monkeypatch.setattr(db, "CONFIG_PATH", tmp_path / "config.json")
    for path, val in (("submission.auto_submit.enabled", True), ("submission.auto_submit.dry_run", False),
                      ("submission.auto_submit.platforms", ["greenhouse", "lever"])):
        cur, new, err = T._validate_config_change(path, val)
        assert err and "not changeable from chat" in err, path
    cur, new, err = T._validate_config_change("submission.max_per_run", 5)
    assert err is None and new == 5


# --- human-verification code gate (operator, 2026-08-31): a board that emails a
# "confirm you're a human" code at submit is a door — learned once, pre-routed
# after, never solved by the head.

def test_gate_key_parses_greenhouse_board():
    assert A.gate_key({"apply_url": "https://job-boards.greenhouse.io/meridiandynamics/jobs/1"}) == "greenhouse:meridiandynamics"
    assert A.gate_key({"job_url": "https://boards.greenhouse.io/meridian/jobs/9"}) == "greenhouse:meridian"


def test_known_human_gate_board_is_refused_before_any_click(scratch_db, row):
    p = _packet(application_id=row["id"], apply_url="https://boards.greenhouse.io/meridian/jobs/1")
    st = {"auto_submit": {"human_verify_gates": ["greenhouse:meridian"]}}
    ok, gate, why = A.eligible(row, p, cfg=_cfg(), state=st, conn=scratch_db, live=True)
    assert not ok and gate == "human_check" and "human" in why.lower()
    # a different board on the same platform is unaffected
    p2 = _packet(application_id=row["id"], apply_url="https://boards.greenhouse.io/cloudmere/jobs/2")
    assert A.eligible(row, p2, cfg=_cfg(), state=st, conn=scratch_db, live=True)[0]
