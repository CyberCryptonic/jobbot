"""GreenhouseForm (real Playwright) against the local fake Greenhouse page.
Includes the PAUSE re-proof on the real browser path (plan §6.3d): zero POSTs
reach the server when PAUSE is present, zero in dry run, exactly one live."""
import hashlib
import json
import time

import pytest

import db
import autosubmit as A
from sources import common
from conftest import add_job
from fake_greenhouse import FakeGreenhouse

pytestmark = pytest.mark.browser

LOCAL = ("127.0.0.1",)


def _cfg(**over):
    c = {"enabled": True, "dry_run": True, "platforms": ["greenhouse"], "tiers": ["A", "B"],
         "verify_first_n": 20, "max_live_per_run": 3, "headless": True, "nav_timeout_s": 6}
    c.update(over)
    return c


@pytest.fixture(scope="module")
def server():
    with FakeGreenhouse() as s:
        yield s


@pytest.fixture
def env(scratch_db, tmp_path, monkeypatch, browser_ok):
    conn = scratch_db
    monkeypatch.setattr(db, "PAUSE_FILE", tmp_path / "PAUSE")
    monkeypatch.setattr(db, "pipeline_paused", lambda: None)
    monkeypatch.setattr(common, "STATE_PATH", tmp_path / "state.json")
    resume = tmp_path / "Resume-FINAL.pdf"; resume.write_bytes(b"%PDF-1.4 resume bytes")
    letter = tmp_path / "1-fake-co.pdf"; letter.write_bytes(b"%PDF-1.4 letter bytes")
    jid = add_job(conn, "Fake Co", "SOC Analyst", location="Boston, MA", score=90, tier="A", status="queued")
    row = conn.execute("SELECT * FROM applications WHERE id=?", (jid,)).fetchone()
    sha = lambda p: hashlib.sha256(p.read_bytes()).hexdigest()
    prof = lambda label, name, req=True: {"label": label, "required": req, "fill": "autofill", "value": A.PROFILE,
                                          "source": "Jobright profile", "inputs": [{"name": name, "type": "input_text", "values": []}]}
    sel = lambda label, name, value, opts, sec: {"label": label, "required": True, "fill": "value", "value": value,
                                                 "source": f"answer file §{sec}",
                                                 "inputs": [{"name": name, "type": "multi_value_single_select", "values": opts}]}
    packet = {
        "application_id": jid, "company": "Fake Co", "role": "SOC Analyst", "platform": "greenhouse",
        "apply_url": None, "decision": "ready", "captcha": False,
        "fields": [
            prof("First Name", "first_name"), prof("Last Name", "last_name"), prof("Email", "email"), prof("Phone", "phone", False),
            {"label": "Resume/CV", "required": False, "fill": "attach", "value": resume.name, "source": "resume, unmodified",
             "inputs": [{"name": "resume", "type": "input_file", "values": []}, {"name": "resume_text", "type": "textarea", "values": []}]},
            {"label": "Cover Letter", "required": False, "fill": "attach", "value": letter.name, "source": "letters/ (Layer 5)", "letter_field": True,
             "inputs": [{"name": "cover_letter", "type": "input_file", "values": []}]},
            prof("LinkedIn Profile", "question_1", False),
            sel("CLEARANCE ELIGIBILITY", "question_2", "Yes, I am eligible for a U.S. security clearance",
                ["Yes, I hold an active U.S. security clearance", "Yes, I am eligible for a U.S. security clearance", "No"], "F"),
            sel("HISTORY WITH MERIDIAN", "question_3", "No", ["Yes", "No"], "E"),
            sel("How did you hear about Meridian?", "question_4", "LinkedIn", ["Google job search", "Indeed", "LinkedIn"], "H"),
            {"label": "Anything else?", "required": False, "fill": "text", "value": "Line one.\nLine two.", "source": "answer file §H",
             "inputs": [{"name": "question_5", "type": "textarea", "values": []}]},
        ],
        "attachments": [{"file": resume.name, "sha256": sha(resume), "role": "resume (byte-for-byte)"},
                        {"file": letter.name, "sha256": sha(letter), "role": "cover letter"}],
        "inferred_answers": [], "gaps": [],
    }
    ident = {"first_name": "Alex", "last_name": "Rivera", "email": "applicant@example.org", "phone": "8455550100",
             "linkedin": "https://linkedin.com/in/alexrivera"}
    return {"conn": conn, "row": row, "packet": packet, "ident": ident, "resume": resume, "letter": letter,
            "shots": tmp_path / "shots", "pause": tmp_path / "PAUSE"}


def _run(env, url, *, cfg, live, factory=None, state=None):
    env["packet"]["apply_url"] = url
    state = state if state is not None else {}
    factory = factory or (lambda cfg: A.GreenhouseForm(cfg, allowed_hosts=LOCAL))
    with db.Run("submission", conn=env["conn"]) as run:
        out = A.run_head(env["conn"], run, env["row"], env["packet"], ident=env["ident"], cfg=cfg, state=state,
                         driver_factory=factory, live=live, shot_dir=env["shots"],
                         resume_path=env["resume"], letter_path=env["letter"])
    return out, state


def _row(env):
    return env["conn"].execute("SELECT status, next_action FROM applications WHERE id=?", (env["row"]["id"],)).fetchone()


def _log(env, action):
    return env["conn"].execute("SELECT * FROM activity_log WHERE action=? ORDER BY id", (action,)).fetchall()


def test_dry_run_fills_everything_screenshots_and_posts_nothing(env, server):
    out, _ = _run(env, server.url("dry"), cfg=_cfg(), live=False)
    assert out == "dryrun"
    assert server.posts.get("dry") is None
    shot = env["shots"] / f"{env['row']['id']}-filled.png"
    assert shot.exists() and shot.stat().st_size > 5000
    detail = json.loads(_log(env, "autosubmit_dryrun")[0]["detail"])
    assert {r["name"]: r["status"] for r in detail["fill_report"]} == {
        "first_name": "filled", "last_name": "filled", "email": "filled", "phone": "filled", "resume": "filled",
        "cover_letter": "filled", "question_1": "filled", "question_2": "filled", "question_3": "filled",
        "question_4": "filled", "question_5": "filled"}
    assert _row(env)["status"] == "queued"


def test_live_posts_exactly_once_with_the_planned_values(env, server):
    out, state = _run(env, server.url("live"), cfg=_cfg(dry_run=False), live=True)
    assert out == "applied"
    posts = server.posts["live"]
    assert len(posts) == 1
    p = posts[0]
    assert p["first_name"] == "Alex" and p["email"] == "applicant@example.org"
    assert p["question_2"] == "Yes, I am eligible for a U.S. security clearance"
    assert p["question_3"] == "No" and p["question_4"] == "LinkedIn"
    assert p["resume"]["filename"] == "Resume-FINAL.pdf" and p["resume"]["size"] == len(b"%PDF-1.4 resume bytes")
    assert p["cover_letter"]["filename"] == "1-fake-co.pdf"
    assert "Line one." in p["question_5"]
    assert _row(env)["status"] == "applied"
    assert (env["shots"] / f"{env['row']['id']}-confirmed.png").exists()
    assert state["auto_submit"]["live_count"] == 1 and not state["auto_submit"]["awaiting_review"]


# --- PAUSE re-proof on the real browser path ---------------------------------------

def test_pause_before_run_posts_nothing_and_launches_nothing(env, server):
    env["pause"].touch()
    launched = []
    def factory(cfg):
        launched.append(1)
        return A.GreenhouseForm(cfg, allowed_hosts=LOCAL)
    out, _ = _run(env, server.url("p1"), cfg=_cfg(dry_run=False), live=True, factory=factory)
    assert out == "paused" and launched == [] and server.posts.get("p1") is None
    assert _log(env, "submit_click") == []


def test_pause_during_fill_posts_nothing(env, server):
    class Paused(A.GreenhouseForm):
        def fill(self, actions):
            r = super().fill(actions)
            env["pause"].touch()                    # the operator touches PAUSE while the form is being filled
            return r
    out, _ = _run(env, server.url("p2"), cfg=_cfg(dry_run=False), live=True,
                  factory=lambda cfg: Paused(cfg, allowed_hosts=LOCAL))
    assert out == "paused" and server.posts.get("p2") is None
    assert (env["shots"] / f"{env['row']['id']}-filled.png").exists()
    assert _log(env, "submit_click") == [] and _row(env)["status"] == "queued"


def test_chat_pause_during_fill_posts_nothing(env, server, monkeypatch):
    class Paused(A.GreenhouseForm):
        def fill(self, actions):
            r = super().fill(actions)
            monkeypatch.setattr(db, "pipeline_paused", lambda: {"paused": True, "by": "chat", "since": "now", "reason": "t"})
            return r
    out, _ = _run(env, server.url("p3"), cfg=_cfg(dry_run=False), live=True,
                  factory=lambda cfg: Paused(cfg, allowed_hosts=LOCAL))
    assert out == "paused" and server.posts.get("p3") is None and _log(env, "submit_click") == []


# --- the door -----------------------------------------------------------------------

def test_challenge_on_the_form_page_is_blocked_before_any_click(env, server):
    out, _ = _run(env, server.url("c1", challenge="before"), cfg=_cfg(dry_run=False), live=True)
    assert out == "blocked:captcha" and server.posts.get("c1") is None
    assert (env["shots"] / f"{env['row']['id']}-blocked.png").exists()
    assert _log(env, "submit_click") == []


def test_challenge_after_click_is_unknown_and_never_retried(env, server):
    out, _ = _run(env, server.url("c2", challenge="after"), cfg=_cfg(dry_run=False), live=True)
    assert out == "unknown" and server.posts.get("c2") is None
    r = _row(env)
    assert r["status"] == "queued" and r["next_action"].startswith("CHECK:")
    assert "challenge" in _log(env, "autosubmit_unknown")[0]["reason"]


def test_login_wall_is_blocked(env, server):
    out, _ = _run(env, server.url("l1", login=1), cfg=_cfg(), live=False)
    assert out == "blocked:login" and server.posts.get("l1") is None


def test_server_error_after_click_is_unknown(env, server):
    out, _ = _run(env, server.url("e1", error=1), cfg=_cfg(dry_run=False), live=True)
    assert out == "unknown" and len(server.posts["e1"]) == 1
    assert "error" in _log(env, "autosubmit_unknown")[0]["reason"].lower()


def test_hung_submit_is_unknown_after_timeout(env, server):
    t0 = time.monotonic()
    out, _ = _run(env, server.url("h1", hang=1), cfg=_cfg(dry_run=False, nav_timeout_s=5), live=True)
    assert out == "unknown" and server.posts.get("h1") is None
    assert time.monotonic() - t0 < 40


def test_unlisted_host_is_never_opened(env, server):
    out, _ = _run(env, server.url("n1"), cfg=_cfg(), live=False,
                  factory=lambda cfg: A.GreenhouseForm(cfg))            # default allow-list, no 127.0.0.1
    assert out == "blocked:navigation" and server.posts.get("n1") is None


def test_option_missing_on_the_real_form_stops_before_click(env, server):
    env["packet"]["fields"][8]["inputs"][0]["values"] = ["Yes", "No", "Maybe"]
    env["packet"]["fields"][8]["value"] = "Maybe"                         # the schema said so; the form does not offer it
    out, _ = _run(env, server.url("o1"), cfg=_cfg(dry_run=False), live=True)
    assert out == "blocked:form" and server.posts.get("o1") is None
    assert "option_not_found" in _log(env, "autosubmit_blocked")[0]["reason"]


def test_assessment_on_confirmation_raises_exception(env, server, monkeypatch):
    import notify
    pushed = []
    monkeypatch.setattr(notify, "push", lambda *a, **k: pushed.append(a) or True)
    out, _ = _run(env, server.url("a1", assessment=1), cfg=_cfg(dry_run=False), live=True)
    assert out == "applied"
    ex = env["conn"].execute("SELECT exception_type FROM applications WHERE id=?", (env["row"]["id"],)).fetchone()
    assert ex["exception_type"] == "assessment" and pushed


def test_phone_country_selector_is_set_when_the_form_has_one(env, server):
    """Review finding #3: the phone Country react-select is chosen from identity.json."""
    env["ident"]["country"] = "United States"
    out, _ = _run(env, server.url("cty"), cfg=_cfg(), live=False)
    assert out == "dryrun"
    detail = json.loads(_log(env, "autosubmit_dryrun")[0]["detail"])
    phone = next(r for r in detail["fill_report"] if r["name"] == "phone")
    assert phone["status"] == "filled" and "country=United States" in phone["detail"]


def test_phone_country_not_offered_is_an_error_not_a_guess(env, server):
    env["ident"]["country"] = "Atlantis"
    out, _ = _run(env, server.url("cty2"), cfg=_cfg(dry_run=False), live=True)
    assert out == "blocked:form" and server.posts.get("cty2") is None
    assert "country" in _log(env, "autosubmit_blocked")[0]["reason"]


def test_value_wiped_by_a_later_rerender_is_repaired_before_screenshot_and_post(env, server):
    """The live React race (2026-08-29): a later widget change reset first/last
    name after they had read back correctly. The driver must notice, re-fill,
    and the POST must carry the repaired value."""
    out, _ = _run(env, server.url("wipe", wipe="first_name"), cfg=_cfg(dry_run=False), live=True)
    assert out == "applied"
    p = server.posts["wipe"][0]
    assert p["first_name"] == "Alex"
    detail = json.loads(_log(env, "submit_click")[0]["detail"])
    fn = next(r for r in detail["fill_report"] if r["name"] == "first_name")
    assert fn["status"] == "filled" and "re-filled" in fn["detail"]


def test_head_refuses_to_click_when_the_form_drifts_at_click_time(env, server, monkeypatch):
    class Drift(A.GreenhouseForm):
        def verify(self, actions):
            self.page.evaluate("document.getElementById('email').value=''")
            return super().verify(actions)
    out, _ = _run(env, server.url("drift"), cfg=_cfg(dry_run=False), live=True,
                  factory=lambda cfg: Drift(cfg, allowed_hosts=LOCAL))
    assert out == "blocked:form" and server.posts.get("drift") is None
    assert _log(env, "submit_click") == []
    assert "form changed after filling" in _log(env, "autosubmit_blocked")[0]["reason"]


# --- the standard Location (City) lookup (a live ATS location-lookup bounce, 2026-09-01) ---

def test_live_fills_the_standard_location_lookup_from_identity(env, server):
    """The widget never appears in probes/packets; the head synthesizes the
    fill from identity.json and the driver types, waits for suggestions, and
    picks the one matching the city — never a decoy place."""
    env["ident"]["city"] = "Rivertown"
    env["ident"]["state"] = "NY"
    out, _ = _run(env, server.url("loc", location=1), cfg=_cfg(dry_run=False), live=True)
    assert out == "applied"
    p = server.posts["loc"][0]
    assert p["candidate-location"] == "Rivertown, New York, United States"
    assert _row(env)["status"] == "applied"


def test_required_location_with_no_identity_city_blocks_before_the_click(env, server):
    """identity.json without city/state must never produce a doomed click:
    the head hands off with evidence instead (the live 09-01 failure mode)."""
    out, _ = _run(env, server.url("locmiss", location=1), cfg=_cfg(dry_run=False), live=True)
    assert out == "blocked:form"
    assert server.posts.get("locmiss") is None
    assert _log(env, "submit_click") == []
