"""autosubmit.run_head with a fake driver: the PAUSE re-proof (plan §6.3 a–c),
write-ahead submit_click, dry run never clicks, unknown state never re-clicks,
verification-window state. No browser, no network."""
import hashlib
import json

import pytest

import db
import autosubmit as A
from sources import common
from conftest import add_job


class FakeDriver:
    """Records every call. `on_fill` runs inside fill() (used to drop the PAUSE
    file mid-form). `outcome_kind` is what the page shows after the click."""
    def __init__(self, conn=None, on_fill=None, open_raises=None, challenge=False, outcome_kind="confirmed",
                 fill_status="filled"):
        self.calls, self.conn, self.on_fill, self.open_raises = [], conn, on_fill, open_raises
        self.challenge, self.outcome_kind, self.fill_status = challenge, outcome_kind, fill_status
        self.submit_click_seen_at_submit = None

    def open(self, url):
        self.calls.append(("open", url))
        if self.open_raises:
            raise self.open_raises
    def fill(self, actions):
        self.calls.append(("fill", len(actions)))
        if self.on_fill:
            self.on_fill()
        return [{"name": a["name"], "status": self.fill_status, "detail": ""} for a in actions]
    def screenshot(self, path):
        self.calls.append(("screenshot", path.name))
        path.write_bytes(b"\x89PNG fake")
    def challenge_visible(self):
        return self.challenge
    def submit(self):
        if self.conn is not None:        # write-ahead proof: the row must exist before the click
            self.submit_click_seen_at_submit = self.conn.execute(
                "SELECT COUNT(*) c FROM activity_log WHERE action='submit_click'").fetchone()["c"]
        self.calls.append(("submit",))
    def outcome(self, timeout_s):
        return self.outcome_kind, {"confirmed": "Thank you for applying", "challenge": "", "error": "There was an error",
                                   "unknown": ""}[self.outcome_kind]
    def page_text(self):
        return "Thank you for applying. We will be in touch."
    def close(self):
        self.calls.append(("close",))


def _cfg(**over):
    c = {"enabled": True, "dry_run": True, "platforms": ["greenhouse"], "tiers": ["A", "B"],
         "verify_first_n": 20, "max_live_per_run": 3, "headless": True, "nav_timeout_s": 5}
    c.update(over)
    return c


@pytest.fixture
def env(scratch_db, tmp_path, monkeypatch):
    """A queued Greenhouse row, a packet whose every field is fillable, an
    identity, a resume, and PAUSE/state redirected into tmp_path."""
    conn = scratch_db
    monkeypatch.setattr(db, "PAUSE_FILE", tmp_path / "PAUSE")
    monkeypatch.setattr(db, "pipeline_paused", lambda: None)
    monkeypatch.setattr(common, "STATE_PATH", tmp_path / "state.json")
    resume = tmp_path / "resume.pdf"; resume.write_bytes(b"%PDF r")
    letter = tmp_path / "letter.pdf"; letter.write_bytes(b"%PDF l")
    jid = add_job(conn, "Meridian Dynamics", "Security Operations Analyst", location="Boston, MA", score=82,
                  tier="A", status="queued", url="https://boards.greenhouse.io/meridian/jobs/1")
    row = conn.execute("SELECT * FROM applications WHERE id=?", (jid,)).fetchone()
    packet = {
        "application_id": jid, "company": row["company"], "role": row["role"], "platform": "greenhouse",
        "apply_url": "https://job-boards.greenhouse.io/meridian/jobs/1", "decision": "ready", "captcha": False,
        "fields": [
            {"label": "First Name", "required": True, "fill": "autofill", "value": A.PROFILE, "source": "Jobright profile",
             "inputs": [{"name": "first_name", "type": "input_text", "values": []}]},
            {"label": "Email", "required": True, "fill": "autofill", "value": A.PROFILE, "source": "Jobright profile",
             "inputs": [{"name": "email", "type": "input_text", "values": []}]},
            {"label": "Resume/CV", "required": False, "fill": "attach", "value": "resume.pdf", "source": "resume, unmodified",
             "inputs": [{"name": "resume", "type": "input_file", "values": []}]},
            {"label": "HISTORY WITH MERIDIAN", "required": True, "fill": "value", "value": "No", "source": "answer file §E",
             "inputs": [{"name": "question_1", "type": "multi_value_single_select", "values": ["Yes", "No"]}]},
        ],
        "attachments": [{"file": "resume.pdf", "sha256": hashlib.sha256(resume.read_bytes()).hexdigest(), "role": "resume (byte-for-byte)"},
                        {"file": "letter.pdf", "sha256": hashlib.sha256(letter.read_bytes()).hexdigest(), "role": "cover letter"}],
        "inferred_answers": [], "gaps": [],
    }
    ident = {"first_name": "N", "last_name": "P", "email": "applicant@example.org"}
    return {"conn": conn, "row": row, "packet": packet, "ident": ident, "resume": resume, "letter": letter,
            "shots": tmp_path / "shots", "pause": tmp_path / "PAUSE", "tmp": tmp_path}


def _run(env, driver, *, cfg, live, state=None):
    state = state if state is not None else {}
    with db.Run("submission", conn=env["conn"]) as run:
        out = A.run_head(env["conn"], run, env["row"], env["packet"], ident=env["ident"], cfg=cfg, state=state,
                         driver_factory=lambda cfg: driver, live=live, shot_dir=env["shots"],
                         resume_path=env["resume"], letter_path=env["letter"])
    return out, state


def _status(env):
    r = env["conn"].execute("SELECT status, next_action, date_applied FROM applications WHERE id=?", (env["row"]["id"],)).fetchone()
    return r["status"], r["next_action"], r["date_applied"]


def _actions(env, name):
    return env["conn"].execute("SELECT * FROM activity_log WHERE action=? ORDER BY id", (name,)).fetchall()


# --- the PAUSE re-proof --------------------------------------------------------

def test_pause_before_run_means_no_browser(env):
    env["pause"].touch()
    d = FakeDriver()
    out, _ = _run(env, d, cfg=_cfg(dry_run=False), live=True)
    assert out == "paused"
    assert d.calls == []                                     # never launched, never opened
    assert _actions(env, "submit_click") == [] and _status(env)[0] == "queued"


def test_pause_between_fill_and_click_means_no_click(env):
    d = FakeDriver(conn=env["conn"], on_fill=lambda: env["pause"].touch())
    out, _ = _run(env, d, cfg=_cfg(dry_run=False), live=True)
    assert out == "paused"
    kinds = [c[0] for c in d.calls]
    assert "fill" in kinds and "screenshot" in kinds and "submit" not in kinds
    assert _actions(env, "submit_click") == [] and _status(env)[0] == "queued"
    assert _actions(env, "autosubmit_paused")[0]["outcome"] == "skip"


def test_chat_pause_between_fill_and_click_means_no_click(env, monkeypatch):
    def flip():
        monkeypatch.setattr(db, "pipeline_paused", lambda: {"paused": True, "since": "now", "by": "chat", "reason": "test"})
    d = FakeDriver(conn=env["conn"], on_fill=flip)
    out, _ = _run(env, d, cfg=_cfg(dry_run=False), live=True)
    assert out == "paused" and ("submit",) not in d.calls
    assert _actions(env, "submit_click") == []


# --- dry run ---------------------------------------------------------------------

def test_dry_run_fills_and_screenshots_but_never_clicks(env):
    d = FakeDriver(conn=env["conn"])
    out, state = _run(env, d, cfg=_cfg(dry_run=True), live=False)
    assert out == "dryrun"
    kinds = [c[0] for c in d.calls]
    assert kinds == ["open", "fill", "screenshot", "close"]
    assert _status(env)[0] == "queued" and _actions(env, "submit_click") == []
    row = _actions(env, "autosubmit_dryrun")[0]
    assert row["outcome"] == "ok" and "-filled.png" in row["reason"]
    detail = json.loads(row["detail"])
    assert "applicant@example.org" not in row["detail"] and "<identity:email>" in row["detail"]
    assert state.get("auto_submit", {}).get("live_count", 0) == 0
    assert (env["shots"] / f"{env['row']['id']}-filled.png").exists()


# --- live ------------------------------------------------------------------------

def test_live_click_is_write_ahead_logged_and_confirms(env):
    d = FakeDriver(conn=env["conn"])
    out, state = _run(env, d, cfg=_cfg(dry_run=False), live=True)
    assert out == "applied"
    assert d.submit_click_seen_at_submit == 1                 # the row existed before the click
    assert [c[0] for c in d.calls] == ["open", "fill", "screenshot", "submit", "screenshot", "close"]
    status, na, applied = _status(env)
    assert status == "applied" and applied and na is None
    st = state["auto_submit"]
    # verification, not a gate (operator, 2026-09-01): a live send screenshots
    # its work but never parks the head
    assert st["live_count"] == 1 and st["live_this_run"] == 1 and st["awaiting_review"] is False
    assert (env["shots"] / f"{env['row']['id']}-confirmed.png").exists()
    ok = _actions(env, "autosubmit_ok")
    assert ok and ok[0]["outcome"] == "ok"
    saved = json.loads(common.STATE_PATH.read_text())          # persisted before the click, not just at the end
    assert saved["auto_submit"]["live_count"] == 1


def test_unknown_state_after_click_never_reclicks(env):
    d = FakeDriver(conn=env["conn"], outcome_kind="unknown")
    out, state = _run(env, d, cfg=_cfg(dry_run=False), live=True)
    assert out == "unknown"
    status, na, _ = _status(env)
    assert status == "queued" and na.startswith("CHECK:") and "do not resubmit" in na
    assert _actions(env, "autosubmit_unknown")[0]["outcome"] == "warn"
    assert state["auto_submit"]["live_count"] == 1
    # a second pass over the same row is refused by the submit_click gate
    d2 = FakeDriver(conn=env["conn"])
    row = env["conn"].execute("SELECT * FROM applications WHERE id=?", (env["row"]["id"],)).fetchone()
    env["row"] = row
    out2, _ = _run(env, d2, cfg=_cfg(dry_run=False), live=True, state=state)
    assert out2 == "refused:submit_click" and d2.calls == []


def test_challenge_rendered_after_click_is_the_door(env):
    d = FakeDriver(conn=env["conn"], outcome_kind="challenge")
    out, _ = _run(env, d, cfg=_cfg(dry_run=False), live=True)
    assert out == "unknown"
    assert (env["shots"] / f"{env['row']['id']}-blocked.png").exists()
    assert "challenge" in _actions(env, "autosubmit_unknown")[0]["reason"].lower()


def test_visible_challenge_before_click_routes_to_manual(env):
    d = FakeDriver(conn=env["conn"], challenge=True)
    out, _ = _run(env, d, cfg=_cfg(dry_run=False), live=True)
    assert out == "blocked:challenge" and ("submit",) not in d.calls
    assert _actions(env, "submit_click") == [] and _status(env)[0] == "queued"
    assert _actions(env, "autosubmit_blocked")[0]["outcome"] == "warn"


def test_blocked_at_open_is_logged_with_a_screenshot(env):
    d = FakeDriver(open_raises=A.Blocked("login", "sign-in page"))
    out, _ = _run(env, d, cfg=_cfg(dry_run=True), live=False)
    assert out == "blocked:login"
    assert ("screenshot", f"{env['row']['id']}-blocked.png") in d.calls
    assert "sign-in page" in _actions(env, "autosubmit_blocked")[0]["reason"]


def test_form_differs_from_schema_stops_before_click(env):
    d = FakeDriver(conn=env["conn"], fill_status="missing")
    out, _ = _run(env, d, cfg=_cfg(dry_run=False), live=True)
    assert out == "blocked:form" and ("submit",) not in d.calls


def test_gaps_are_recorded_and_live_never_launches(env):
    env["packet"]["fields"][3]["value"] = "None"               # not one of Yes / No
    d = FakeDriver()
    out, _ = _run(env, d, cfg=_cfg(dry_run=False), live=True)
    assert out == "gaps" and d.calls == []
    gap = env["conn"].execute("SELECT question FROM answer_gaps").fetchone()["question"]
    assert "HISTORY WITH MERIDIAN" in gap and "Yes / No" in gap
    assert _actions(env, "submit_click") == []


def test_dry_run_with_gaps_still_fills_the_rest_for_review(env):
    env["packet"]["fields"][3]["value"] = "None"
    d = FakeDriver(conn=env["conn"])
    out, _ = _run(env, d, cfg=_cfg(dry_run=True), live=False)
    assert out == "gaps"
    assert [c[0] for c in d.calls] == ["open", "fill", "screenshot", "close"]
    assert ("fill", 3) in d.calls                              # the three fillable actions, not the gap
    assert (env["shots"] / f"{env['row']['id']}-filled.png").exists()
    assert "[DRY RUN]" in _actions(env, "autosubmit_gaps")[0]["reason"]


def test_refused_gate_logs_and_does_not_launch(env):
    d = FakeDriver()
    out, _ = _run(env, d, cfg=_cfg(enabled=False), live=False)
    assert out == "refused:enabled" and d.calls == []
    assert _actions(env, "autosubmit_skip")[0]["reason"].startswith("enabled:")


def test_launch_failure_is_unavailable_not_silent(env):
    def boom(cfg):
        raise RuntimeError("libnss3 missing")
    with db.Run("submission", conn=env["conn"]) as run:
        out = A.run_head(env["conn"], run, env["row"], env["packet"], ident=env["ident"], cfg=_cfg(), state={},
                         driver_factory=boom, live=False, shot_dir=env["shots"], resume_path=env["resume"], letter_path=env["letter"])
    assert out == "unavailable"
    assert _actions(env, "autosubmit_unavailable")[0]["outcome"] == "warn"


def test_verification_window_ends_at_n(env):
    d = FakeDriver(conn=env["conn"])
    state = {"auto_submit": {"live_count": 20, "awaiting_review": False}}
    out, state = _run(env, d, cfg=_cfg(dry_run=False, verify_first_n=20), live=True, state=state)
    assert out == "applied" and state["auto_submit"]["awaiting_review"] is False
    assert [c[0] for c in d.calls] == ["open", "fill", "submit", "screenshot", "close"]   # no filled-form shot after #20


def test_confirmation_mentioning_an_assessment_raises_the_exception(env, monkeypatch):
    class D(FakeDriver):
        def page_text(self):
            return "Thanks! Next step: complete the HackerRank assessment within 5 days."
    pushed = []
    import notify
    monkeypatch.setattr(notify, "push", lambda *a, **k: pushed.append(a) or True)
    d = D(conn=env["conn"])
    out, _ = _run(env, d, cfg=_cfg(dry_run=False), live=True)
    assert out == "applied"
    r = env["conn"].execute("SELECT exception_type FROM applications WHERE id=?", (env["row"]["id"],)).fetchone()
    assert r["exception_type"] == "assessment" and pushed


# --- human-verification code gate: a door, learned and un-counted --------------

class HumanCheckDriver(FakeDriver):
    """Post-click the board shows an emailed 'confirm you're a human' code."""
    def outcome(self, timeout_s):
        return "unknown", ("A verification code was sent to your email. To submit your "
                           "application, enter the 8-character code to confirm you're a human.")


def test_human_verification_code_page_routes_to_manual_learns_board_and_uncounts(env):
    d = HumanCheckDriver(conn=env["conn"])
    out, state = _run(env, d, cfg=_cfg(dry_run=False), live=True)
    assert out == "blocked:human_check"
    # the click did happen (write-ahead row stays; the head never re-clicks this row)
    assert len(_actions(env, "submit_click")) == 1
    # but no application was submitted: the send is rolled back, the run is not jammed
    st = state["auto_submit"]
    assert st["live_count"] == 0 and st["live_this_run"] == 0 and st["awaiting_review"] is False
    # the board is learned so its other jobs pre-route without a click
    assert "greenhouse:meridian" in st.get("human_verify_gates", [])
    # routed to the operator's manual lane, not left as a resubmit-forbidden CHECK
    status, na, _ = _status(env)
    assert status == "queued" and na.startswith("AGENT-HANDOFF")
    assert _actions(env, "autosubmit_human_check")[0]["outcome"] == "warn"
    assert (env["shots"] / f"{env['row']['id']}-blocked.png").exists()


def test_human_check_pushes_and_emails_an_immediate_code_alert(env, monkeypatch):
    pushes, emails = [], []
    import notify, mailer
    monkeypatch.setattr(notify, "push", lambda *a, **k: pushes.append((a, k)) or True)
    monkeypatch.setattr(mailer, "send", lambda *a, **k: emails.append((a, k)) or True)
    monkeypatch.setattr(db, "ENV", {**db.ENV, "REPORT_TO": "applicant@example.org"})
    d = HumanCheckDriver(conn=env["conn"])
    out, _ = _run(env, d, cfg=_cfg(dry_run=False), live=True)
    assert out == "blocked:human_check"
    assert pushes and emails                                  # phone push AND email fired
    apply_url = env["packet"]["apply_url"]
    assert any(apply_url in str(a) + str(k) for a, k in pushes)   # the finish link is in the push
    alert = _actions(env, "code_needed_alert")
    assert alert and alert[0]["outcome"] == "ok"
