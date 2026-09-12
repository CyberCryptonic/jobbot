"""submission.process() with the head wired in. Form probes and the browser
are faked; the resume hash is real. Checks the two counters stay separate and
that only applied/unknown outcomes skip today's handoff."""
import json

import pytest

import db
import autosubmit as A
import submission as S
from sources import common
from conftest import add_job

GH_FORM = {"platform": "greenhouse", "status": "read", "apply_url": "https://job-boards.greenhouse.io/fakeco/jobs/1",
           "captcha": False, "eeoc_questions": 0,
           "fields": [
               {"label": "First Name", "required": True, "kind": "input_text", "options": [],
                "inputs": [{"name": "first_name", "type": "input_text", "values": []}]},
               {"label": "Email", "required": True, "kind": "input_text", "options": [],
                "inputs": [{"name": "email", "type": "input_text", "values": []}]},
               {"label": "HISTORY WITH FAKECO", "required": True, "kind": "multi_value_single_select", "options": ["Yes", "No"],
                "inputs": [{"name": "question_1", "type": "multi_value_single_select", "values": ["Yes", "No"]}]},
           ]}


class Driver:
    def __init__(self, outcome="confirmed"):
        self.outcome_kind, self.calls = outcome, []
    def open(self, url): self.calls.append("open")
    def fill(self, actions): self.calls.append("fill"); return [{"name": a["name"], "status": "filled", "detail": ""} for a in actions]
    def screenshot(self, path): path.write_bytes(b"png")
    def challenge_visible(self): return False
    def submit(self): self.calls.append("submit")
    def outcome(self, t): return self.outcome_kind, "Thank you for applying"
    def page_text(self): return "Thank you for applying"
    def close(self): pass


@pytest.fixture
def wired(scratch_db, tmp_path, monkeypatch):
    conn = scratch_db
    monkeypatch.setattr(db, "PAUSE_FILE", tmp_path / "PAUSE")
    monkeypatch.setattr(db, "pipeline_paused", lambda: None)
    monkeypatch.setattr(common, "STATE_PATH", tmp_path / "state.json")
    monkeypatch.setattr(S, "probe_form", lambda url: json.loads(json.dumps(GH_FORM)))
    monkeypatch.setattr(S, "SUB_DIR", tmp_path / "submissions")
    monkeypatch.setattr(S, "SHOT_DIR", tmp_path / "screenshots")
    monkeypatch.setattr(S, "DRY_RUN", False)
    monkeypatch.setattr(A, "load_identity", lambda *a, **k: {"first_name": "N", "last_name": "P", "email": "applicant@example.org"})
    driver = Driver()
    monkeypatch.setattr(A, "driver_for", lambda platform, cfg, **k: driver)
    jid = add_job(conn, "FakeCo", "SOC Analyst", location="Boston, MA", score=90, tier="A", status="queued",
                  url="https://boards.greenhouse.io/fakeco/jobs/1")
    return {"conn": conn, "jid": jid, "driver": driver, "tmp": tmp_path}


def _rows(conn, jid):
    return conn.execute("SELECT * FROM applications WHERE id=?", (jid,)).fetchall()


def _acts(conn):
    return [r["action"] for r in conn.execute("SELECT action FROM activity_log ORDER BY id")]


def _process(w, cfg):
    S.AUTO.clear(); S.AUTO.update(cfg)
    with db.Run("submission", conn=w["conn"]) as run:
        rows = w["conn"].execute("SELECT * FROM applications WHERE id=?", (w["jid"],)).fetchall()
        return S.process(run, w["conn"], rows)


def test_disabled_head_changes_nothing(wired):
    counts = _process(wired, {"enabled": False})
    acts = _acts(wired["conn"])
    assert "submit_handoff" in acts and not any(a.startswith("autosubmit") for a in acts)
    assert wired["driver"].calls == []
    assert counts["ready"] == 1


def test_dry_run_head_then_handoff_as_today(wired):
    counts = _process(wired, {"enabled": True, "dry_run": True, "platforms": ["greenhouse"]})
    acts = _acts(wired["conn"])
    assert acts.index("autosubmit_dryrun") < acts.index("submit_handoff")
    assert wired["driver"].calls == ["open", "fill"]
    r = _rows(wired["conn"], wired["jid"])[0]
    assert r["status"] == "queued" and r["next_action"].startswith("AGENT-HANDOFF")
    assert counts.get("auto_dryrun") == 1
    st = json.loads(common.STATE_PATH.read_text())
    assert "verified" not in st.get("submission", {})             # handoffs no longer advance any verification counter
    assert st.get("auto_submit", {}).get("live_count", 0) == 0    # the real counter untouched by a dry run


def test_live_applied_skips_the_handoff(wired):
    counts = _process(wired, {"enabled": True, "dry_run": False, "platforms": ["greenhouse"]})
    acts = _acts(wired["conn"])
    assert "autosubmit_ok" in acts and "submit_handoff" not in acts
    r = _rows(wired["conn"], wired["jid"])[0]
    assert r["status"] == "applied" and r["next_action"] is None
    st = json.loads(common.STATE_PATH.read_text())
    assert st["auto_submit"]["live_count"] == 1 and st["auto_submit"]["awaiting_review"] is False  # head never self-stops
    assert "verified" not in st.get("submission", {})            # no separate handoff counter exists any more
    assert counts.get("auto_applied") == 1


def test_unknown_outcome_skips_the_handoff_and_leaves_a_check_note(wired):
    wired["driver"].outcome_kind = "unknown"
    _process(wired, {"enabled": True, "dry_run": False, "platforms": ["greenhouse"]})
    r = _rows(wired["conn"], wired["jid"])[0]
    assert r["status"] == "queued" and r["next_action"].startswith("CHECK:")
    assert "submit_handoff" not in _acts(wired["conn"])


def test_submission_dry_run_flag_forces_head_dry_run(wired, monkeypatch):
    monkeypatch.setattr(S, "DRY_RUN", True)
    _process(wired, {"enabled": True, "dry_run": False, "platforms": ["greenhouse"]})
    acts = _acts(wired["conn"])
    assert "autosubmit_dryrun" in acts and "submit_click" not in acts and "submit_dryrun" in acts


def test_reviewed_clears_the_self_stop(wired):
    common.save_state({"auto_submit": {"live_count": 3, "awaiting_review": True}})
    n = S.mark_reviewed(wired["conn"])
    st = json.loads(common.STATE_PATH.read_text())
    assert st["auto_submit"]["awaiting_review"] is False and n == 3
    assert "review_ack" in _acts(wired["conn"])


def test_gaps_from_the_head_land_in_answer_gaps_and_handoff_continues(wired, monkeypatch):
    form = json.loads(json.dumps(GH_FORM))
    form["fields"][2]["inputs"][0]["values"] = ["Yes", "No"]
    monkeypatch.setattr(S, "probe_form", lambda url: form)
    monkeypatch.setattr(S.answers, "load", lambda: {"E": {"Previously employed here": "None"}, "ID": {"Work authorization": "authorized"}, "_titles": {}, "_notes": {}})
    counts = _process(wired, {"enabled": True, "dry_run": False, "platforms": ["greenhouse"]})
    gaps = [r["question"] for r in wired["conn"].execute("SELECT question FROM answer_gaps")]
    assert any("HISTORY WITH FAKECO" in g and "Yes / No" in g for g in gaps)
    acts = _acts(wired["conn"])
    assert "autosubmit_gaps" in acts and "submit_handoff" in acts and "submit_click" not in acts
    assert counts.get("auto_gaps") == 1


# --- review finding #1: a CHECK row must never be re-handed off ---------------------

def test_check_rows_are_not_reselected_for_the_morning_batch(wired):
    conn, jid = wired["conn"], wired["jid"]
    conn.execute("UPDATE applications SET next_action='CHECK: submit clicked, confirmation not seen — do not resubmit' WHERE id=?", (jid,))
    other = add_job(conn, "OtherCo", "SOC Analyst", location="X", score=80, tier="A", status="queued",
                    url="https://boards.greenhouse.io/otherco/jobs/2")
    ids = [r["id"] for r in S.select_rows(conn)]
    assert other in ids and jid not in ids


def test_refused_submit_click_never_overwrites_the_check_note(wired):
    conn, jid = wired["conn"], wired["jid"]
    db.log("submission", "submit_click", run_id="t", application_id=jid, conn=conn)
    conn.execute("UPDATE applications SET next_action='CHECK: submit clicked, confirmation not seen — do not resubmit' WHERE id=?", (jid,))
    counts = _process(wired, {"enabled": True, "dry_run": False, "platforms": ["greenhouse"]})
    r = _rows(conn, jid)[0]
    assert r["next_action"].startswith("CHECK:")                      # note kept
    acts = _acts(conn)
    assert "submit_handoff" not in acts and "autosubmit_skip" in acts
    assert wired["driver"].calls == []
    assert counts.get("auto_refused") == 1


# --- an enabled head takes over packets that are waiting on the operator ---------------

def test_pending_handoffs_are_selected_only_when_the_head_is_enabled(wired):
    conn, jid = wired["conn"], wired["jid"]
    conn.execute("UPDATE applications SET next_action='AGENT-HANDOFF: open in browser, Jobright autofill completes the form' WHERE id=?", (jid,))
    assert jid not in [r["id"] for r in S.select_rows(conn, head_enabled=False)]
    assert jid in [r["id"] for r in S.select_rows(conn, head_enabled=True)]
    conn.execute("UPDATE applications SET next_action='CHECK: submit clicked, confirmation not seen — do not resubmit' WHERE id=?", (jid,))
    assert jid not in [r["id"] for r in S.select_rows(conn, head_enabled=True)]


def test_dry_run_on_a_pending_handoff_does_not_relog_the_handoff(wired):
    conn, jid = wired["conn"], wired["jid"]
    conn.execute("UPDATE applications SET next_action='AGENT-HANDOFF: open in browser, Jobright autofill completes the form' WHERE id=?", (jid,))
    _process(wired, {"enabled": True, "dry_run": True, "platforms": ["greenhouse"]})
    acts = _acts(conn)
    assert "autosubmit_dryrun" in acts and "submit_handoff" not in acts
    r = _rows(conn, jid)[0]
    assert r["status"] == "queued" and r["next_action"].startswith("AGENT-HANDOFF")


def test_live_on_a_pending_handoff_applies(wired):
    conn, jid = wired["conn"], wired["jid"]
    conn.execute("UPDATE applications SET next_action='AGENT-HANDOFF: open in browser, Jobright autofill completes the form' WHERE id=?", (jid,))
    _process(wired, {"enabled": True, "dry_run": False, "platforms": ["greenhouse"]})
    r = _rows(conn, jid)[0]
    assert r["status"] == "applied" and r["next_action"] is None


# --- the verification window counts only actual submit_click sends (operator, 2026-08-31) ---

def test_handoff_form_record_does_not_count_as_verification(wired):
    _process(wired, {"enabled": True, "dry_run": True, "platforms": ["greenhouse"]})
    st = json.loads(common.STATE_PATH.read_text())
    assert "verified" not in st.get("submission", {})
    row = wired["conn"].execute("SELECT reason FROM activity_log WHERE action='form_record'").fetchone()
    assert row is not None
    assert "live sends 0/" in row["reason"] and "verification" not in row["reason"]


def test_capture_window_closes_after_verify_first_n_live_sends(wired):
    common.save_state({"auto_submit": {"live_count": 20, "live_this_run": 0, "awaiting_review": False}})
    _process(wired, {"enabled": False})
    acts = _acts(wired["conn"])
    assert "submit_handoff" in acts and "form_record" not in acts


def test_stale_verified_counter_is_dropped_from_state(wired):
    common.save_state({"submission": {"verified": 18}})
    _process(wired, {"enabled": False})
    st = json.loads(common.STATE_PATH.read_text())
    assert "verified" not in st.get("submission", {})


def test_optional_self_id_miss_does_not_block_a_live_send(wired, monkeypatch):
    form = json.loads(json.dumps(GH_FORM))
    form["fields"].append({"label": "Race", "required": False, "kind": "multi_value_single_select",
                           "demographic": True, "options": ["Decline To Self Identify", "White"],
                           "inputs": [{"name": "race", "type": "multi_value_single_select",
                                       "values": ["Decline To Self Identify", "White"]}]})
    monkeypatch.setattr(S, "probe_form", lambda url: form)
    driver = wired["driver"]
    def fill(actions):
        driver.calls.append("fill")
        return [{"name": a["name"], "status": "missing" if a["name"] == "race" else "filled",
                 "detail": "no such input" if a["name"] == "race" else ""} for a in actions]
    driver.fill = fill
    _process(wired, {"enabled": True, "dry_run": False, "platforms": ["greenhouse"]})
    r = _rows(wired["conn"], wired["jid"])[0]
    assert r["status"] == "applied"                                  # the miss did not block
    click = wired["conn"].execute("SELECT detail FROM activity_log WHERE action='submit_click'").fetchone()
    assert click is not None and '"race"' in click["detail"]         # but the fill was planned and attempted


def test_learned_human_gate_board_routes_to_handoff_without_a_click(wired):
    common.save_state({"auto_submit": {"human_verify_gates": ["greenhouse:fakeco"]}})
    counts = _process(wired, {"enabled": True, "dry_run": False, "platforms": ["greenhouse"]})
    acts = _acts(wired["conn"])
    assert "submit_handoff" in acts and "submit_click" not in acts
    assert wired["driver"].calls == []                       # the browser never launched
    assert "autosubmit_skip" in acts
    skip = wired["conn"].execute("SELECT reason FROM activity_log WHERE action='autosubmit_skip'").fetchone()
    assert "human_check" in skip["reason"]


def test_answer_gaps_fire_one_consolidated_reach_out(wired, monkeypatch):
    form = json.loads(json.dumps(GH_FORM))
    form["fields"][2]["inputs"][0]["values"] = ["Yes", "No"]
    monkeypatch.setattr(S, "probe_form", lambda url: form)
    monkeypatch.setattr(S.answers, "load", lambda: {"E": {"Previously employed here": "None"},
                        "ID": {"Work authorization": "authorized"}, "_titles": {}, "_notes": {}})
    pushes, emails = [], []
    import notify, mailer
    monkeypatch.setattr(notify, "push", lambda *a, **k: pushes.append((a, k)) or True)
    monkeypatch.setattr(mailer, "send", lambda *a, **k: emails.append((a, k)) or True)
    monkeypatch.setattr(db, "ENV", {**db.ENV, "REPORT_TO": "applicant@example.org"})
    _process(wired, {"enabled": True, "dry_run": False, "platforms": ["greenhouse"]})
    assert pushes and emails                                  # exactly one reach-out, both channels
    alert = wired["conn"].execute("SELECT reason FROM activity_log WHERE action='gaps_alert'").fetchall()
    assert len(alert) == 1 and "HISTORY WITH FAKECO" in alert[0]["reason"]


def test_a_stored_answer_closes_the_gap_and_the_field_fills_next_run(wired, monkeypatch):
    # simulate the operator answering: the question is now in the answer bank (§M).
    form = json.loads(json.dumps(GH_FORM))
    form["fields"][2]["inputs"][0]["values"] = ["Yes", "No"]
    monkeypatch.setattr(S, "probe_form", lambda url: form)
    monkeypatch.setattr(S.answers, "load", lambda: {"M": {"HISTORY WITH FAKECO": "No"},
                        "ID": {"Work authorization": "authorized"}, "_titles": {}, "_notes": {}})
    d = S.map_field(form["fields"][2], {"cover_letter_path": None, "company": "FakeCo", "source": "company_page"},
                    S.answers.load(), {})
    assert d.get("value") == "No" and d["fill"] in ("value", "text")   # the stored answer now fills, no gap
