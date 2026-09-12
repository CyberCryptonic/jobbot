"""Layer 6b — the autonomous ATS submit head (session 9, 2026-08-29).

Runs inside the 08:00 submission stage, right after submission.py has built a
packet. For a READY packet on a supported ATS (Greenhouse first) it drives the
real application form with Playwright, deterministically and auditably:

    packet ─► eligible() ─► plan_fill() ─► driver.fill() ─► screenshot
                                                       └─► dry run: stop here
                                                       └─► live: may_submit() ─► submit_click row ─► click ─► confirmation

Everything that does not pass every gate takes today's path instead: the
packet is handed to the operator on the dashboard Agent lane (that IS the
"route to manual"). Nothing here ever solves a captcha, logs in, or retries a
click.

Gates (config.json -> submission.auto_submit):
  enabled false          the head never launches a browser
  dry_run true           fill + screenshot, never click
  platforms              ["greenhouse"] to start; Lever/Ashby/Workable stay out
                         until a dry-run screenshot on a real posting is reviewed
  tiers                  ["A","B"]
  verify_first_n         the first N live sends screenshot both the filled form
                         and the confirmation for the nightly report —
                         verification, not a gate (operator cleared the
                         self-stop ramp 2026-09-01; `submission.py --reviewed`
                         remains only to clear a manually/legacy-set
                         awaiting_review flag)
  max_live_per_run       live sends per run inside that window

Fill rules (plan_fill):
  - identity (name, email, phone, links) comes only from identity.json
    (mode 600, git-ignored; email must equal MAIL_ADDRESS so replies land in
    the inbox Layer 7 reads)
  - a select answer must equal one of the form's own options after
    normalisation; anything else is an answer gap with the options quoted
  - an inferred answer (§L rule 2) is never filled by this head
  - attestation-class labels (export control, citizenship, clearance, work
    authorization, salary, experience, criminal, education) need an explicit
    "answer file §X" source
  - attachments are re-hashed against the packet before they are attached

Identity values never reach activity_log: redact() replaces them with
"<identity:key>" before a plan is logged.
"""

import hashlib
import json
import os
import re
import stat
from pathlib import Path

import db

CONFIG = json.loads((db.BASE_DIR / "config.json").read_text())
ACFG = CONFIG.get("submission", {}).get("auto_submit", {})
IDENTITY_PATH = db.BASE_DIR / "identity.json"
RESUME = db.RESUME_PATH
PROFILE = "identity block (identity.json for the autonomous head; Jobright autofill on manual handoff)"   # the packet's marker for profile fields

DEFAULTS = {"enabled": False, "dry_run": True, "platforms": ["greenhouse"], "tiers": ["A", "B"],
            "verify_first_n": 20, "max_live_per_run": 3, "headless": True, "nav_timeout_s": 45}


def cfg_get(cfg, key):
    return (cfg or {}).get(key, DEFAULTS[key])


# ---------------------------------------------------------------------------
# identity.json
# ---------------------------------------------------------------------------

class IdentityError(Exception):
    pass


IDENTITY_REQUIRED = ("first_name", "last_name", "email")


def load_identity(path=None, env=None):
    """The only source of name / email / phone / links for the head. Refuses a
    file that is world- or group-readable, and an email that is not the pipeline
    inbox the pipeline reads."""
    path = Path(path or IDENTITY_PATH)
    env = env if env is not None else db.ENV
    if not path.exists():
        raise IdentityError(f"{path.name} missing (copy config/identity.example.json to identity.json, chmod 600)")
    mode = stat.S_IMODE(path.stat().st_mode)
    if mode & 0o077:
        raise IdentityError(f"{path.name} mode is {oct(mode)}; must be 0600")
    try:
        ident = json.loads(path.read_text())
    except ValueError as e:
        raise IdentityError(f"{path.name} is not valid JSON: {e}")
    for k in IDENTITY_REQUIRED:
        if not str(ident.get(k, "")).strip():
            raise IdentityError(f"{path.name} lacks '{k}'")
    ident = {k: str(v).strip() for k, v in ident.items() if v is not None and str(v).strip()}
    want = (env.get("MAIL_ADDRESS") or "").strip().lower()
    if ident["email"].lower() != want:
        raise IdentityError(f"{path.name} email does not equal MAIL_ADDRESS; replies would miss the inbox Layer 7 reads")
    ident["email"] = ident["email"].lower()
    return ident


# label -> identity key. Education never maps: it is an attestation with no
# identity source, so it becomes a gap.
IDENTITY_MAP = [
    (r"^first name$|^given name$", "first_name"),
    (r"^last name$|^surname$|^family name$", "last_name"),
    (r"^(full )?name$|^legal name$|^full legal name$|^first and last name$", "full_name"),
    (r"^e-?mail( address)?$", "email"),
    (r"^phone( number)?$|^mobile|^telephone", "phone"),
    (r"linkedin", "linkedin"),
    (r"github", "github"),
    (r"portfolio|personal website|^website( or blog)?$|website/portfolio", "website"),
    (r"current location|^location$|city", "location"),
    (r"current company|current employer|^company$", "current_company"),
]


def identity_value(label, ident):
    """(value, key) for a profile-marked field, or (None, key|None)."""
    low = (label or "").strip().lower()
    for rx, key in IDENTITY_MAP:
        if re.search(rx, low):
            if key == "full_name":
                if ident.get("first_name") and ident.get("last_name"):
                    return f"{ident['first_name']} {ident['last_name']}", key
                return None, key
            if key == "location":
                parts = [ident.get("city"), ident.get("state")]
                if all(parts):
                    return ", ".join(parts), key
                return None, key
            return ident.get(key), key
    return None, None


# ---------------------------------------------------------------------------
# options and attestations
# ---------------------------------------------------------------------------

def norm_option(s):
    s = (s or "").lower().replace("–", "-").replace("—", "-").replace("’", "'")
    s = re.sub(r"[^a-z0-9]+", " ", s)
    return " ".join(s.split())


def match_option(value, options):
    """The one option whose normalised text equals the answer's, else None.
    Never a prefix, never a fuzzy pick: 'None' is not 'No'."""
    want = norm_option(value)
    if not want:
        return None
    hits = [o for o in options if norm_option(o) == want]
    return hits[0] if len(hits) == 1 else None


# Auto-acknowledge (operator policy 2026-08-31): the head may tick routine
# consent/privacy/agree-to-terms fields on its own. It must NOT auto-sign the
# weighty legal attestations — a background-check authorization, an I-9, or an
# "I certify ... true under penalty" statement — those stay gaps and route to
# manual (the exception-queue rule). CERTIFY wins over ACK.
ACK_RX = re.compile(r"acknowledg|consent|privacy|agree to|i agree|\bterms\b|i accept|i understand|opt.?in", re.I)
CERTIFY_RX = re.compile(r"background check|background investigation|\bi-?9\b|penalty of perjury|certify (that|the)|"
                        r"electronic signature|e-?sign|under penalty|authoriz\w* a background|true and (complete|correct)", re.I)


def is_auto_ack(label):
    return bool(ACK_RX.search(label or "")) and not CERTIFY_RX.search(label or "")


def pick_ack_option(options):
    """The affirmative choice on an acknowledgment field: an explicit
    acknowledge/agree/accept option, or the sole option of a tick-to-proceed
    checkbox. None when nothing affirmative is offered."""
    aff = re.compile(r"acknowledg|confirm|i agree|\bagree\b|accept|i understand|^yes\b|opt.?in", re.I)
    hits = [o for o in options if o and aff.search(o)]
    if hits:
        return hits[0]
    return options[0] if len(options) == 1 and options[0] else None


ATTEST_RX = re.compile(
    r"export control|u\.?s\.? person|citizen|national|clearance|authoriz|sponsorship|visa|"
    r"salary|compensation|desired pay|years of|experience|felony|convict|criminal|"
    r"degree|education|university|school|graduat", re.I)

EXPLICIT_SOURCE_RX = re.compile(r"^answer file §[A-Z]+\b|^current employer\b")


def attestation(label):
    return bool(ATTEST_RX.search(label or ""))


def explicit_source(field):
    return bool(EXPLICIT_SOURCE_RX.search(field.get("source") or "")) and not field.get("inferred")


# ---------------------------------------------------------------------------
# plan_fill — packet fields -> concrete actions, gaps, refusals
# ---------------------------------------------------------------------------

def _input_of(field, types):
    for inp in field.get("inputs") or []:
        if inp.get("type") in types:
            return inp
    return None


def _options(field):
    for inp in field.get("inputs") or []:
        if inp.get("values"):
            return list(inp["values"])
    return list(field.get("options") or [])


def _gap(field, kind, note):
    opts = _options(field)
    q = field["label"].strip()
    if opts:
        q += " (options: " + " / ".join(opts) + ")"
    if note:
        q += f" — {note}"
    return {"kind": kind, "label": field["label"], "question": q[:900], "required": bool(field.get("required"))}


def _sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def plan_fill(packet, ident, *, resume_path=RESUME, letter_path=None):
    """Deterministic. Returns
        {"actions": [...], "gaps": [...], "refusals": [...], "ok": bool}
    actions: {"type": "text"|"select"|"attach", "name", "label", "source", "value"|"option"|"path"}
    gaps:    answer gaps to record (each routes the packet to manual)
    refusals: structural problems (resume drift, no input for a field)
    A packet is fillable (ok) only with zero gaps and zero refusals."""
    actions, gaps, refusals = [], [], []
    att = {a["role"].split(" (")[0]: a for a in packet.get("attachments", [])}

    for f in packet.get("fields") or []:
        fill = f.get("fill")
        label = f.get("label", "")
        required = bool(f.get("required"))
        opts = _options(f)

        # auto-acknowledge routine consents before the gap checks: tick the
        # affirmative option regardless of the stored answer's exact wording
        # (operator policy 2026-08-31). Legal attestations are excluded and
        # fall through to the normal gap logic.
        if is_auto_ack(label) and opts:
            chosen = pick_ack_option(opts)
            if chosen is not None:
                inp = _input_of(f, ("multi_value_single_select", "multi_value_multi_select", "select",
                                    "radio", "checkbox", "boolean")) or (f.get("inputs") or [None])[0]
                if inp:
                    kind = "check" if inp.get("type") in ("multi_value_multi_select", "checkbox") else "select"
                    actions.append({"type": kind, "name": inp["name"], "option": chosen, "label": label,
                                    "source": "auto-acknowledge (operator policy 2026-08-31)"})
                    continue

        if fill == "blank":
            if required:
                gaps.append(_gap(f, "uncovered", "required, answer file has nothing"))
            continue
        if fill == "GAP":
            gaps.append(_gap(f, "uncovered", f.get("source")))
            continue
        if f.get("inferred"):
            gaps.append(_gap(f, "inferred", f"the packet inferred '{f.get('value')}' ({f.get('source')}); this head fills only sourced answers"))
            continue

        if fill == "autofill":
            val, key = identity_value(label, ident or {})
            if key is None or attestation(label) and key not in ("location", "current_company"):
                gaps.append(_gap(f, "attestation_unsourced" if attestation(label) else "identity",
                                 "profile field with no identity.json key"))
                continue
            if val is None:
                if required:
                    gaps.append(_gap(f, "identity", f"identity.json has no '{key}'"))
                continue
            inp = _input_of(f, ("input_text", "textarea", "lever", "text", "email", "tel", "url")) or (f.get("inputs") or [None])[0]
            if not inp:
                refusals.append(f"no input for '{label}'")
                continue
            act = {"type": "text", "name": inp["name"], "value": val, "label": label,
                   "source": f"identity.json:{key}"}
            if key == "phone" and ident.get("country"):
                act["country"] = ident["country"]      # for a phone widget with its own country selector
            actions.append(act)
            continue

        if fill == "attach":
            role = "resume" if "resume" in (f.get("source") or "").lower() else "cover letter"
            inp = _input_of(f, ("input_file", "file"))
            if not inp:
                refusals.append(f"no file input for '{label}'")
                continue
            if role == "resume":
                path = Path(resume_path)
                expect = att.get("resume", {}).get("sha256")
                if not path.exists() or not expect or _sha(path) != expect:
                    refusals.append("resume on disk does not match the packet's sha256; refusing to attach")
                    continue
            else:
                path = Path(letter_path) if letter_path else None
                expect = att.get("cover letter", {}).get("sha256")
                if not path or not path.exists() or not expect or _sha(path) != expect:
                    if required:
                        gaps.append(_gap(f, "uncovered", "cover letter missing or changed since the packet was built"))
                    continue
            actions.append({"type": "attach", "name": inp["name"], "path": str(path), "label": label,
                            "source": f.get("source")})
            continue

        if fill in ("value", "text"):
            if attestation(label) and not explicit_source(f):
                gaps.append(_gap(f, "attestation_unsourced",
                                 f"attestation needs an explicit answer-file row (source was '{f.get('source')}')"))
                continue
            value = f.get("value")
            if fill == "text" and "cover letter text" in str(value):
                gaps.append(_gap(f, "uncovered", "letter text field: not supported by this head yet"))
                continue
            if opts:
                chosen = match_option(value, opts)
                if chosen is None:
                    gaps.append(_gap(f, "option_mismatch", f"answer file says '{value}', not one of the options"))
                    continue
                inp = _input_of(f, ("multi_value_single_select", "multi_value_multi_select", "select", "radio",
                                    "checkbox", "boolean", "lever")) or (f.get("inputs") or [None])[0]
                if not inp:
                    refusals.append(f"no select input for '{label}'")
                    continue
                act = {"type": "select", "name": inp["name"], "option": chosen, "label": label,
                       "source": f.get("source")}
                if f.get("demographic"):
                    act["optional"] = True   # voluntary self-ID: attempted, never a door
                actions.append(act)
                continue
            inp = _input_of(f, ("textarea",) if fill == "text" or "\n" in str(value) else ("input_text", "text", "textarea", "lever")) \
                or _input_of(f, ("input_text", "textarea", "text", "lever")) or (f.get("inputs") or [None])[0]
            if not inp:
                refusals.append(f"no text input for '{label}'")
                continue
            actions.append({"type": "text", "name": inp["name"], "value": str(value), "label": label,
                            "source": f.get("source")})
            continue

        refusals.append(f"unknown fill kind '{fill}' for '{label}'")

    # Greenhouse's standard Location (City) lookup never appears in probes or
    # packets (its input has no name; recon 2026-09-01). The head synthesizes
    # the fill from identity.json; the driver no-ops when the form has none.
    if (ident or {}).get("city") and (ident or {}).get("state"):
        actions.append({"type": "location", "name": "candidate-location",
                        "value": f"{ident['city']}, {ident['state']}",
                        "label": "Location (City)", "source": "identity.json (city, state)"})

    return {"actions": actions, "gaps": gaps, "refusals": refusals,
            "ok": not gaps and not refusals}


def redact(plan):
    """A copy of the plan safe for activity_log: identity values replaced by
    their key, file paths kept (they are inside the project)."""
    out = json.loads(json.dumps(plan))
    for a in out.get("actions", []):
        src = a.get("source") or ""
        if src.startswith("identity.json:") and "value" in a:
            a["value"] = f"<identity:{src.split(':', 1)[1]}>"
        if "country" in a:
            a["country"] = "<identity:country>"
    return out


# ---------------------------------------------------------------------------
# eligible — the gates that send a packet back to the handoff path
# ---------------------------------------------------------------------------

def gate_key(packet):
    """A stable per-board key for the human-verification gate list. Greenhouse
    boards key on their slug (one company per slug); anything else on host."""
    from urllib.parse import urlparse
    url = packet.get("apply_url") or packet.get("job_url") or ""
    m = re.search(r"greenhouse\.io/([^/?#]+)/", url)
    if m:
        return f"greenhouse:{m.group(1)}"
    host = urlparse(url).netloc.lower()
    return f"host:{host}" if host else ""


def human_verify_gates(state):
    return set((state or {}).get("auto_submit", {}).get("human_verify_gates", []))


def eligible(row, packet, *, cfg, state, conn, live):
    """(ok, gate, reason). `live` applies the verification-window gates."""
    if not cfg_get(cfg, "enabled"):
        return False, "enabled", "auto_submit.enabled is false"
    plat = packet.get("platform")
    if plat not in cfg_get(cfg, "platforms"):
        return False, "platform", f"{plat} is not in auto_submit.platforms"
    if packet.get("decision") != "ready":
        return False, "decision", f"packet decision is {packet.get('decision')}"
    if packet.get("captcha"):
        return False, "captcha", "form has an interactive captcha"
    if gate_key(packet) in human_verify_gates(state):
        return False, "human_check", ("board requires a human-verification code at submit "
                                       "(learned earlier); routed to manual, the head does not solve it")
    if row["suspicious"]:
        return False, "suspicious", "posting flagged for text addressed to automation"
    if row["tier"] not in cfg_get(cfg, "tiers"):
        return False, "tier", f"tier {row['tier']} is not in auto_submit.tiers"
    if db.reapply_counts(conn).get(row["company_norm"], 0) >= 3:
        return False, "reapply", "3 applications to this company already (reapply cap)"
    prior = conn.execute("SELECT ts FROM activity_log WHERE action='submit_click' AND application_id=? LIMIT 1",
                         (row["id"],)).fetchone()
    if prior:
        return False, "submit_click", f"a submit was already clicked for this row at {prior['ts']}; never twice"
    if live:
        st = (state or {}).get("auto_submit", {})
        if st.get("awaiting_review"):
            return False, "awaiting_review", "verification window: earlier live sends await operator review (submission.py --reviewed)"
        n = int(cfg_get(cfg, "verify_first_n") or 0)
        if n and int(st.get("live_count", 0)) < n and int(st.get("live_this_run", 0)) >= int(cfg_get(cfg, "max_live_per_run")):
            return False, "max_live_per_run", f"verification window: {cfg_get(cfg, 'max_live_per_run')} live sends this run already"
    return True, None, "all gates passed"


def may_submit():
    """Re-read both pause signals right now. Called immediately before the
    click, after the form is filled."""
    return not db.kill_switch() and not db.pipeline_paused()


# ---------------------------------------------------------------------------
# The head — one packet, one browser context, one decision
# ---------------------------------------------------------------------------

class Blocked(Exception):
    """The door: a captcha, a login wall, a page that is not the form, a
    refused navigation. kind is short and stable (captcha, login, no_form,
    navigation, challenge, form); detail is for the log."""
    def __init__(self, kind, detail=""):
        super().__init__(f"{kind}: {detail}")
        self.kind, self.detail = kind, detail


"""Driver protocol (GreenhouseForm implements it; tests use a fake):
    open(url)                       -> None; raises Blocked
    fill(actions)                   -> [{"name", "status": filled|missing|option_not_found|error, "detail"}]
    screenshot(path: Path)          -> None
    challenge_visible()             -> bool   (a rendered, interactive captcha / challenge)
    submit()                        -> None   (one click, never repeated)
    outcome(timeout_s)              -> (kind, text)  kind in confirmed|challenge|error|unknown
    page_text()                     -> str
    close()                         -> None
"""

EXCEPTION_RX = [
    ("assessment", re.compile(r"assessment|coding challenge|hackerrank|codility|codesignal|take-?home|skills? test", re.I)),
    ("video_interview", re.compile(r"video interview|hirevue|recorded interview|spark ?hire|one-way interview", re.I)),
]

# A board that, after the submit click, emails a code and asks for it "to
# confirm you're a human" is running a human-verification gate. The head never
# solves it (project rule: never work around bot detection): it screenshots,
# routes the job to the manual lane, and learns the board so its other jobs
# pre-route without a click.
HUMAN_VERIFY_RX = re.compile(
    r"verification code was sent|confirm you'?re a human|enter the \d+-character code"
    r"|enter the code (we )?(sent|emailed)|code to confirm you'?re a human", re.I)


def _shot(driver, shot_dir, name):
    try:
        shot_dir.mkdir(parents=True, exist_ok=True)
        p = shot_dir / name
        driver.screenshot(p)
        return p
    except Exception:
        return None


def _rel(p):
    try:
        return str(p.relative_to(db.BASE_DIR))
    except (ValueError, AttributeError):
        return str(p) if p else None


def run_head(conn, run, row, packet, *, ident, cfg, state, driver_factory, live, shot_dir,
             resume_path=RESUME, letter_path=None, gap_sink=None):
    """Returns one of:
        refused:<gate> | gaps | unavailable | blocked:<kind> | paused | dryrun | applied | unknown
    Only 'applied' and 'unknown' change the tracker. Everything else leaves
    the row exactly as the handoff path expects it."""
    subject = f"{row['company']} — {row['role']}"
    aid = row["id"]
    st = state.setdefault("auto_submit", {})
    st.setdefault("live_count", 0)
    st.setdefault("awaiting_review", False)
    st.setdefault("live_this_run", 0)

    ok, gate, why = eligible(row, packet, cfg=cfg, state=state, conn=conn, live=live)
    if not ok:
        run.log("autosubmit_skip", subject=subject, application_id=aid, outcome="skip", reason=f"{gate}: {why}"[:300])
        return f"refused:{gate}"

    if live and not may_submit():
        run.log("autosubmit_paused", subject=subject, application_id=aid, outcome="skip",
                reason="PAUSE (file or chat flag) present before the browser launched; handed off instead")
        return "paused"

    if ident is None:
        try:
            ident = load_identity()
        except IdentityError as e:
            run.log("autosubmit_unavailable", subject=subject, application_id=aid, outcome="warn",
                    reason=f"identity: {e}; handed off instead"[:300])
            return "unavailable"

    plan = plan_fill(packet, ident, resume_path=resume_path, letter_path=letter_path)
    if gap_sink is not None:
        gap_sink.extend(g["question"] for g in plan["gaps"])
    for g in plan["gaps"]:
        db.upsert_answer_gap(conn, g["question"], application_id=aid)
        run.log("answer_gap", subject=subject, application_id=aid, outcome="warn",
                reason=f"[{g['kind']}] {g['question']}"[:300])
    gap_note = (f"{len(plan['gaps'])} gap(s), {len(plan['refusals'])} refusal(s); handed off instead: "
                + "; ".join([g["label"][:50] for g in plan["gaps"]] + plan["refusals"]))
    if plan["refusals"] or (plan["gaps"] and live):
        run.log("autosubmit_gaps", subject=subject, application_id=aid, outcome="skip",
                reason=gap_note[:300], detail=json.dumps(redact(plan)))
        return "gaps"
    # a DRY RUN with gaps still opens the form and fills what it can, so the
    # operator can review the driver's work on the real page; nothing is sent
    # and the outcome stays 'gaps'

    try:
        driver = driver_factory(cfg)
    except Exception as e:
        run.log("autosubmit_unavailable", subject=subject, application_id=aid, outcome="warn",
                reason=f"browser could not start ({type(e).__name__}: {e}); handed off instead"[:300])
        return "unavailable"

    try:
        try:
            driver.open(packet.get("apply_url") or packet.get("job_url"))
        except Blocked as b:
            shot = _shot(driver, shot_dir, f"{aid}-blocked.png")
            run.log("autosubmit_blocked", subject=subject, application_id=aid, outcome="warn",
                    reason=f"{b.kind}: {b.detail} | record {_rel(shot)}"[:300])
            return f"blocked:{b.kind}"

        report = driver.fill(plan["actions"])
        # a required location lookup the plan could not cover (identity.json
        # without city/state) must never become a doomed click
        if hasattr(driver, "required_location_unfilled") and driver.required_location_unfilled():
            shotL = _shot(driver, shot_dir, f"{aid}-blocked.png")
            db.upsert_answer_gap(conn, "Location (City) — the form's standard location lookup "
                                 "(fill identity.json city/state)", application_id=aid)
            run.log("autosubmit_blocked", subject=subject, application_id=aid, outcome="warn",
                    reason=f"required Location (City) lookup and identity.json has no city/state; handed off | record {_rel(shotL)}"[:300])
            return "blocked:form"
        optional = {a["name"] for a in plan["actions"] if a.get("optional")}
        bad = [r for r in report if r.get("status") != "filled" and r["name"] not in optional]
        opt_miss = [r["name"] for r in report if r.get("status") != "filled" and r["name"] in optional]
        opt_note = f" | voluntary self-ID not fillable, left blank: {', '.join(opt_miss)}" if opt_miss else ""
        n = int(cfg_get(cfg, "verify_first_n") or 0)
        in_window = (not live) or (n and st["live_count"] < n)
        shot = _shot(driver, shot_dir, f"{aid}-filled.png") if (in_window or bad) else None
        if bad:
            run.log("autosubmit_blocked", subject=subject, application_id=aid, outcome="warn",
                    reason=("form differs from the packet schema: "
                            + "; ".join(f"{r['name']} {r['status']} {r.get('detail', '')}".strip() for r in bad)
                            + f" | record {_rel(shot)}")[:300], detail=json.dumps(report))
            return "blocked:form"

        if plan["gaps"]:
            run.log("autosubmit_gaps", subject=subject, application_id=aid, outcome="skip",
                    reason=(f"[DRY RUN] filled {len(report)} field(s), left the gap fields empty | record {_rel(shot)} | "
                            + gap_note)[:300],
                    detail=json.dumps({"plan": redact(plan), "fill_report": report}))
            return "gaps"

        if not live:
            run.log("autosubmit_dryrun", subject=subject, application_id=aid, outcome="ok",
                    reason=(f"[DRY RUN] filled {len(report) - len(opt_miss)} field(s) on {packet.get('platform')}, did not click submit"
                            f" | record {_rel(shot)}{opt_note}")[:300],
                    detail=json.dumps({"plan": redact(plan), "fill_report": report}))
            return "dryrun"

        if driver.challenge_visible():
            shot2 = _shot(driver, shot_dir, f"{aid}-blocked.png")
            run.log("autosubmit_blocked", subject=subject, application_id=aid, outcome="warn",
                    reason=f"challenge: an interactive captcha rendered before submit; handed off | record {_rel(shot2)}"[:300])
            return "blocked:challenge"

        # the last look at the pause signals, after the form is filled
        if not may_submit():
            run.log("autosubmit_paused", subject=subject, application_id=aid, outcome="skip",
                    reason=f"PAUSE appeared while the form was being filled; nothing clicked | record {_rel(shot)}"[:300])
            return "paused"

        # the form must still match the plan at click time
        verify = getattr(driver, "verify", None)
        if verify:
            drift = [r for r in verify(plan["actions"]) if r["name"] not in optional]
            if drift:
                shot5 = _shot(driver, shot_dir, f"{aid}-blocked.png")
                run.log("autosubmit_blocked", subject=subject, application_id=aid, outcome="warn",
                        reason=("form changed after filling, nothing clicked: "
                                + "; ".join(f"{r['name']} {r['status']} {r.get('detail', '')}".strip() for r in drift)
                                + f" | record {_rel(shot5)}")[:300], detail=json.dumps(drift))
                return "blocked:form"

        # write-ahead: the click is recorded before it happens, so a crash in
        # between can never lead to a second click (eligible() gate submit_click)
        st["live_count"] += 1
        st["live_this_run"] += 1
        # verification, not a gate (operator, 2026-09-01): the first
        # verify_first_n sends still screenshot form + confirmation for the
        # nightly report, but the head never parks itself awaiting review
        st["last_live"] = db.now()
        from sources import common
        common.save_state(state)
        run.log("submit_click", subject=subject, application_id=aid, outcome="ok",
                reason=f"clicking submit on {packet.get('platform')} (live send #{st['live_count']})",
                detail=json.dumps({"plan": redact(plan), "fill_report": report}))
        driver.submit()
        kind, text = driver.outcome(int(cfg_get(cfg, "nav_timeout_s")))

        if HUMAN_VERIFY_RX.search(text or "") or HUMAN_VERIFY_RX.search(driver.page_text() or ""):
            # a human-verification code gate rendered after the click. No
            # application was submitted (the form gates on a code the head will
            # not enter). Un-count the write-ahead send so this door does not
            # consume a verification slot or jam the run, learn the board so its
            # other jobs pre-route without a click, and hand this one off.
            shoth = _shot(driver, shot_dir, f"{aid}-blocked.png")
            st["live_count"] = max(0, int(st.get("live_count", 0)) - 1)
            st["live_this_run"] = max(0, int(st.get("live_this_run", 0)) - 1)
            st["awaiting_review"] = False
            gates = st.setdefault("human_verify_gates", [])
            key = gate_key(packet)
            if key and key not in gates:
                gates.append(key)
            common.save_state(state)
            db.set_status(conn, aid, "queued",
                          next_action=("AGENT-HANDOFF: board asks for an emailed verification code to "
                                       "confirm a human; open in browser, enter the code, submit by hand"),
                          append_note=f"auto-submit stopped at a human-verification code gate {db.now()}; handed off")
            run.log("autosubmit_human_check", subject=subject, application_id=aid, outcome="warn",
                    reason=(f"board requires an emailed human-verification code at submit; not solved, "
                            f"handed off and learned ({key}) | record {_rel(shoth)}")[:300])
            _notify_code_needed(conn, run, row, packet.get("apply_url") or packet.get("job_url"))
            return "blocked:human_check"

        if kind == "confirmed":
            shot3 = _shot(driver, shot_dir, f"{aid}-confirmed.png")
            db.set_status(conn, aid, "applied",
                          append_note=f"auto-submitted via {packet.get('platform')} {db.now()}; confirmation: {text[:80]}")
            conn.execute("UPDATE applications SET next_action=NULL WHERE id=?", (aid,))   # set_status(None) means 'keep'
            run.log("autosubmit_ok", subject=subject, application_id=aid, outcome="ok",
                    reason=(f"submitted on {packet.get('platform')}: {text[:120]} | record {_rel(shot3)}"
                            + (f" | verification {st['live_count']}/{n}, self-stopped for review" if st["awaiting_review"] else ""))[:300])
            _check_exceptions(conn, run, row, driver.page_text())
            return "applied"

        shot4 = _shot(driver, shot_dir, f"{aid}-blocked.png")
        db.set_status(conn, aid, "queued",
                      next_action=("CHECK: submit clicked, confirmation not seen — do not resubmit; "
                                   "look for a confirmation email before applying by hand"),
                      append_note=f"auto-submit {kind} after click {db.now()}: {text[:80]}")
        run.log("autosubmit_unknown", subject=subject, application_id=aid, outcome="warn",
                reason=(f"after the click the page showed {kind}: {text[:100] or 'nothing recognisable'}; "
                        f"status left queued with a CHECK note | record {_rel(shot4)}")[:300])
        return "unknown"
    finally:
        try:
            driver.close()
        except Exception:
            pass


def _notify_code_needed(conn, run, row, apply_url):
    """Immediate push + email the moment a job stalls at a human-verification
    code gate: the operator opens the link, enters the code from their inbox,
    and submits by hand. Never blocks; logs whether each channel fired."""
    subject = f"{row['company']} — {row['role']}"
    dash = CONFIG.get("report", {}).get("dashboard_url", "http://localhost")
    link = apply_url or (dash + "/manual")
    title = f"Code needed: {row['company']}"
    body = (f"{row['role']}: this application is filled and waiting on the emailed "
            f"verification code. Open the link, enter the code from your inbox, and submit.")
    push_ok = mail_ok = False
    try:
        import notify
        push_ok = bool(notify.push(title, body, priority=5, tags=["closed_lock_with_key"], click=link))
    except Exception:
        push_ok = False
    try:
        import mailer
        to = db.ENV.get("REPORT_TO") or db.ENV.get("MAIL_ADDRESS")
        if to:
            mailer.send(to, title, f"{body}\n\nFinish here: {link}\n\n"
                        "The code was emailed to you by the employer. jobbot never enters it.")
            mail_ok = True
    except Exception:
        mail_ok = False
    run.log("code_needed_alert", subject=subject, application_id=row["id"],
            outcome="ok" if (push_ok or mail_ok) else "fail",
            reason=f"push={'ok' if push_ok else 'fail'} email={'ok' if mail_ok else 'fail'} | {link}"[:300])


def notify_gaps(run, questions):
    """One consolidated push + email per run when driveable jobs are blocked
    only by answers the bank does not have. The operator answers once (dashboard
    chat / a reply); the answer is stored (answer file §M) and the job auto-
    applies on the next run, and every future form with that question fills."""
    qs = list(dict.fromkeys(q for q in questions if q))[:10]
    if not qs:
        return
    link = CONFIG.get("report", {}).get("dashboard_url", "http://localhost") + "/chat"
    title = f"{len(qs)} answer(s) needed to finish applications"
    body = ("These questions are the only thing blocking hands-off applications. "
            "Answer them in the dashboard chat and the jobs go out on the next "
            "run — and each answer is saved for every future form that asks it:\n\n- "
            + "\n- ".join(qs) + f"\n\nAnswer here: {link}")
    push_ok = mail_ok = False
    try:
        import notify
        push_ok = bool(notify.push(title, "; ".join(qs)[:200], priority=4, tags=["memo"], click=link))
    except Exception:
        push_ok = False
    try:
        import mailer
        to = db.ENV.get("REPORT_TO") or db.ENV.get("MAIL_ADDRESS")
        if to:
            mailer.send(to, title, body)
            mail_ok = True
    except Exception:
        mail_ok = False
    run.log("gaps_alert", outcome="ok" if (push_ok or mail_ok) else "fail",
            reason=f"{len(qs)} question(s) need answers: {'; '.join(qs)[:250]}")


def _check_exceptions(conn, run, row, text):
    """A confirmation page that asks for an assessment or a recorded video
    interview is one of the four interrupts."""
    for ex_type, rx in EXCEPTION_RX:
        if rx.search(text or ""):
            note = f"confirmation page after auto-submit mentions: {rx.search(text).group(0)}"
            db.raise_exception(conn, row["id"], ex_type, note, run_id=run.run_id, stage="submission")
            try:
                import notify
                ok = notify.push(f"{ex_type.replace('_', ' ')}: {row['company']}",
                                 f"{row['role']}: {note}", priority=5, tags=["rotating_light"],
                                 click=CONFIG.get("report", {}).get("dashboard_url", "http://localhost") + "/applications")
            except Exception:
                ok = False
            run.log("ntfy_push", subject=f"{row['company']} — {row['role']}", application_id=row["id"],
                    outcome="ok" if ok else "fail", reason=f"{ex_type} pushed to phone" if ok else "ntfy push failed; exception is on the dashboard")
            return


# ---------------------------------------------------------------------------
# Playwright drivers
# ---------------------------------------------------------------------------

ALLOWED_HOSTS = ("greenhouse.io", "lever.co", "ashbyhq.com", "workable.com")

# an interactive challenge that has actually rendered — the door
CHALLENGE_SEL = ", ".join([
    "iframe[src*='recaptcha/api2/bframe']", "iframe[title*='recaptcha challenge' i]",
    "iframe[src*='hcaptcha.com']", "iframe[title*='hcaptcha' i]",
    "iframe[src*='challenges.cloudflare.com']", "iframe[src*='turnstile']",
    "div.h-captcha:not(:empty)", "[data-hcaptcha-widget-id]",
])
CONFIRM_RX = re.compile(r"thank you for applying|thanks for applying|application (has been |was )?(submitted|received)|"
                        r"we('ve| have) received your application|successfully submitted|application submitted", re.I)
ERROR_RX = re.compile(r"there was an error|something went wrong|please try again|could not be submitted|"
                      r"verify (that )?you are (a )?human|unusual traffic|failed to submit", re.I)
LOGIN_RX = re.compile(r"sign in|log in|login|create an account", re.I)


def _host_ok(url, allowed):
    from urllib.parse import urlparse
    host = (urlparse(url).hostname or "").lower()
    return any(host == h or host.endswith("." + h) for h in allowed)


class PlaywrightDriver:
    """Shared browser plumbing: headless Chromium with its own sandbox on, a
    fresh context, no extensions, nothing persisted, and a main-frame
    navigation allow-list. Sub-resources (fonts, the captcha script) are not
    filtered — only where the page itself may go."""

    def __init__(self, cfg, allowed_hosts=ALLOWED_HOSTS):
        from playwright.sync_api import sync_playwright
        self.allowed = tuple(allowed_hosts)
        self.timeout_ms = int(cfg_get(cfg, "nav_timeout_s")) * 1000
        self.refused = None
        self._pw = sync_playwright().start()
        try:
            self._browser = self._pw.chromium.launch(headless=bool(cfg_get(cfg, "headless")), chromium_sandbox=True)
        except Exception:
            self._pw.stop()
            raise
        self._ctx = self._browser.new_context(viewport={"width": 1280, "height": 1600}, accept_downloads=False)
        self._ctx.set_default_timeout(self.timeout_ms)
        self.page = self._ctx.new_page()
        self._ctx.route("**/*", self._route)

    def _route(self, route):
        req = route.request
        try:
            if req.is_navigation_request() and req.frame == self.page.main_frame and not _host_ok(req.url, self.allowed):
                self.refused = req.url
                return route.abort()
        except Exception:
            pass
        route.continue_()

    def screenshot(self, path):
        self.page.screenshot(path=str(path), full_page=True)

    def challenge_visible(self):
        try:
            loc = self.page.locator(CHALLENGE_SEL)
            for i in range(loc.count()):
                if loc.nth(i).is_visible():
                    return True
        except Exception:
            return False
        return False

    def page_text(self):
        try:
            return self.page.locator("body").inner_text(timeout=5000)[:5000]
        except Exception:
            return ""

    def close(self):
        for f in (lambda: self._ctx.close(), lambda: self._browser.close(), lambda: self._pw.stop()):
            try:
                f()
            except Exception:
                pass


class GreenhouseForm(PlaywrightDriver):
    """Greenhouse job-board application page (job-boards.greenhouse.io).
    Selectors verified against a live form on 2026-08-29:
      #application-form; input#<name> (text, tel); textarea#<name>;
      input#resume / input#cover_letter (type=file, visually hidden);
      react-select: input#<name>[role=combobox] -> #react-select-<name>-listbox [role=option],
      chosen label in the sibling .select__single-value;
      button[type=submit] "Submit application"."""

    FORM = "#application-form"

    def open(self, url):
        if not _host_ok(url, self.allowed):
            raise Blocked("navigation", f"host not allowed: {url[:80]}")
        try:
            self.page.goto(url, wait_until="domcontentloaded")
        except Exception as e:
            raise Blocked("navigation", f"{'refused: ' + self.refused if self.refused else type(e).__name__}"[:120])
        try:
            self.page.wait_for_selector(self.FORM, timeout=min(self.timeout_ms, 30000))
        except Exception:
            text = self.page_text()
            if self.page.locator("input[type=password]").count() or LOGIN_RX.search(self.page.title() or ""):
                raise Blocked("login", "a sign-in page instead of the form")
            if self.challenge_visible():
                raise Blocked("captcha", "a challenge rendered before the form")
            raise Blocked("no_form", f"no application form on the page ({(self.page.title() or text[:60])[:60]})")
        if self.challenge_visible():
            raise Blocked("captcha", "a challenge is showing on the form page")
        # the form's upload settings load after the DOM; a file chosen before
        # that fails with a client-side error (seen live 2026-08-29)
        try:
            self.page.wait_for_load_state("networkidle", timeout=min(self.timeout_ms, 20000))
        except Exception:
            pass

    def _one(self, sel):
        loc = self.page.locator(sel)
        return loc.first if loc.count() else None

    def fill(self, actions):
        report = self._fill_once(actions)
        # Seen live 2026-08-29: text inputs read back correctly right after
        # filling, then a later React re-render reset two of them. Let the
        # page settle, read everything back, re-fill anything that drifted
        # once, and report the state the form is actually in.
        for _ in range(3):
            self.page.wait_for_timeout(1000)
            before = json.dumps(report, sort_keys=True)
            report = self._verify_and_repair(actions, report, repair=True)
            if json.dumps(report, sort_keys=True) == before and not any("re-filled" in r.get("detail", "") and r.get("_fresh") for r in report):
                break
            for r in report:
                r.pop("_fresh", None)
        return report

    def verify(self, actions):
        """Read every text/select action back from the live form; no
        repairs. Called by the head immediately before the click."""
        return [r for r in self._verify_and_repair(actions, None, repair=False) if r["status"] != "filled"]

    def _fill_text(self, el, value):
        """React-controlled inputs on this form sometimes drop a value that an
        in-flight re-render overtakes (seen live 2026-08-29). Fill, give React
        a beat, read back; up to three tries."""
        for _ in range(3):
            el.fill(value)
            self.page.wait_for_timeout(250)
            if self._text_matches(el, value):
                return True
        return False

    def _text_el(self, name):
        return self._one(f"{self.FORM} input#{name}, {self.FORM} textarea#{name}")

    def _text_matches(self, el, value):
        got = el.input_value()
        return got == value or (norm_option(got) == norm_option(value) and norm_option(value) != "")

    def _select_value(self, name):
        chosen = self._one(f"xpath=//input[@id='{name}']/ancestor::div[contains(@class,'select__value-container')]"
                           f"//div[contains(@class,'select__single-value')]")
        return chosen.inner_text().strip() if chosen is not None else ""

    def _fill_location(self, a):
        """The standard Location (City) lookup (input#candidate-location,
        react-select with async suggestions; live recon 2026-09-01): type the
        identity city, wait for suggestions, pick the one matching the city —
        never a decoy place. A form without the widget is simply satisfied."""
        name, value = a["name"], a["value"]
        el = self._one(f"{self.FORM} input#{name}")
        if el is None:
            return {"name": name, "status": "filled", "detail": "form has no standard location lookup"}
        if self._select_value(name):
            return {"name": name, "status": "filled", "detail": "already chosen"}
        city = norm_option(value.split(",")[0])
        for attempt in range(2):
            el.click()
            el.fill("")
            el.type(value, delay=30)
            try:
                self.page.wait_for_selector(f"[id^='react-select-{name}-option-']",
                                            timeout=9000, state="visible")
            except Exception:
                continue
            opts = self.page.locator(f"[id^='react-select-{name}-option-']")
            pick = None
            for i in range(min(opts.count(), 8)):
                o = opts.nth(i)
                if norm_option(o.inner_text()).startswith(city):
                    pick = o
                    break
            if pick is None:
                return {"name": name, "status": "error",
                        "detail": f"no location suggestion matched '{value.split(',')[0]}'"}
            pick.dispatch_event("mousedown")      # react-select chooses on mousedown
            self.page.wait_for_timeout(350)
            got = self._select_value(name)
            if norm_option(got).startswith(city):
                return {"name": name, "status": "filled", "detail": f"picked '{got[:60]}'"}
        return {"name": name, "status": "error", "detail": "location suggestions never appeared"}

    def required_location_unfilled(self):
        """True when the form shows a required standard location lookup that
        still has no chosen value (the head must hand off, never click)."""
        el = self._one(f"{self.FORM} input#candidate-location")
        if el is None or self._select_value("candidate-location"):
            return False
        lab = self._one("#candidate-location-label")
        return (el.get_attribute("aria-required") == "true") or \
               bool(lab is not None and "*" in (lab.inner_text() or ""))

    def _verify_and_repair(self, actions, report, repair):
        by = {r["name"]: r for r in (report or [])}
        out = []
        for a in actions:
            name, typ = a["name"], a["type"]
            prev = by.get(name, {"name": name, "status": "filled", "detail": ""})
            if prev.get("status") != "filled":
                out.append(prev); continue
            try:
                if typ == "text":
                    el = self._text_el(name)
                    ok = el is not None and self._text_matches(el, a["value"])
                    if not ok and repair and el is not None:
                        ok = self._fill_text(el, a["value"])
                        prev = dict(prev, detail=(prev.get("detail", "") + " re-filled after the page reset it").strip(), _fresh=True)
                    if not ok:
                        prev = {"name": name, "status": "error", "detail": "value lost after fill (page reset it)"}
                elif typ == "select":
                    ok = norm_option(self._select_value(name)) == norm_option(a["option"])
                    if not ok and repair:
                        prev = self._select(name, a["option"])
                        ok = prev["status"] == "filled"
                    if not ok and prev.get("status") == "filled":
                        prev = {"name": name, "status": "error", "detail": "selection lost after fill (page reset it)"}
                elif typ == "check":
                    ok = self._checkbox_checked(name, a["option"])
                    if not ok and repair:
                        prev = self._checkbox(name, a["option"])
                        ok = prev["status"] == "filled"
                    if not ok and prev.get("status") == "filled":
                        prev = {"name": name, "status": "error", "detail": "checkbox lost after fill (page reset it)"}
                elif typ == "location":
                    absent = self._one(f"{self.FORM} input#{name}") is None
                    city = norm_option(a["value"].split(",")[0])
                    ok = absent or norm_option(self._select_value(name)).startswith(city)
                    if not ok and repair:
                        prev = self._fill_location(a)
                        ok = prev["status"] == "filled"
                    if not ok and prev.get("status") == "filled":
                        prev = {"name": name, "status": "error", "detail": "location choice lost after fill (page reset it)"}
                # attachments: the file chip is checked at upload time; a page reset would drop the form entirely
            except Exception as e:
                prev = {"name": name, "status": "error", "detail": f"verify: {type(e).__name__}: {e}"[:120]}
            out.append(prev)
        return out

    def _fill_once(self, actions):
        report = []
        for a in actions:
            name, typ = a["name"], a["type"]
            try:
                if typ == "text":
                    el = self._text_el(name)
                    if el is None:
                        report.append({"name": name, "status": "missing", "detail": "no such input"}); continue
                    ok = self._fill_text(el, a["value"])
                    entry = {"name": name, "status": "filled" if ok else "error",
                             "detail": "" if ok else "readback differs after 3 attempts"}
                    if entry["status"] == "filled" and a.get("country"):
                        entry = self._country(entry, a["country"])
                    report.append(entry)
                elif typ == "attach":
                    el = self._one(f"{self.FORM} input#{name}[type=file]")
                    if el is None:
                        report.append({"name": name, "status": "missing", "detail": "no file input"}); continue
                    el.set_input_files(a["path"])
                    base = Path(a["path"]).name
                    try:
                        self.page.get_by_text(base, exact=False).first.wait_for(timeout=10000)
                        report.append({"name": name, "status": "filled", "detail": base})
                    except Exception:
                        report.append({"name": name, "status": "error", "detail": "file name not shown after upload"})
                elif typ == "select":
                    report.append(self._select(name, a["option"]))
                elif typ == "check":
                    report.append(self._checkbox(name, a["option"]))
                elif typ == "location":
                    report.append(self._fill_location(a))
                else:
                    report.append({"name": name, "status": "error", "detail": f"unknown action {typ}"})
            except Exception as e:
                report.append({"name": name, "status": "error", "detail": f"{type(e).__name__}: {e}"[:120]})
        return report

    def _checkbox_el(self, name, option):
        """A checkbox (Greenhouse renders multi-select as input[type=checkbox]
        with an array name like 'question_N[]'). Match by option label, or the
        sole box of a tick-to-proceed field. Attribute selector, so the '[]' in
        the name is not a broken #id selector."""
        boxes = self.page.locator(f'{self.FORM} input[type=checkbox][name="{name}"]')
        n = boxes.count()
        want = norm_option(option)
        for i in range(n):
            el = boxes.nth(i)
            try:
                lab = el.evaluate("e => { const l = e.closest('label') || "
                                  "document.querySelector(`label[for='${e.id}']`); return l ? l.innerText : ''; }")
            except Exception:
                lab = ""
            if norm_option(lab) == want or (n == 1 and not want):
                return el
            if n == 1:
                return el
        return None

    def _checkbox(self, name, option):
        el = self._checkbox_el(name, option)
        if el is None:
            return {"name": name, "status": "option_not_found", "detail": f"no checkbox '{option}'"}
        try:
            if not el.is_checked():
                el.check()
            return {"name": name, "status": "filled" if el.is_checked() else "error",
                    "detail": option if el.is_checked() else "could not check"}
        except Exception as e:
            return {"name": name, "status": "error", "detail": f"check: {type(e).__name__}: {e}"[:120]}

    def _checkbox_checked(self, name, option):
        el = self._checkbox_el(name, option)
        try:
            return el is not None and el.is_checked()
        except Exception:
            return False

    def _select(self, name, option):
        inp = self._one(f"{self.FORM} input#{name}[role=combobox]")
        if inp is None:
            return {"name": name, "status": "missing", "detail": "no combobox"}
        inp.click()
        inp.fill(option)
        listbox = f"#react-select-{name}-listbox [role=option]"
        try:
            self.page.wait_for_selector(listbox, timeout=10000)
        except Exception:
            return {"name": name, "status": "option_not_found", "detail": "no options rendered"}
        opts = self.page.locator(listbox)
        want = norm_option(option)
        target = None
        for i in range(opts.count()):
            if norm_option(opts.nth(i).inner_text()) == want:
                target = opts.nth(i); break
        if target is None:
            self.page.keyboard.press("Escape")
            return {"name": name, "status": "option_not_found", "detail": f"'{option}' not among the rendered options"}
        target.click()
        chosen = self._one(f"xpath=//input[@id='{name}']/ancestor::div[contains(@class,'select__value-container')]"
                           f"//div[contains(@class,'select__single-value')]")
        got = chosen.inner_text() if chosen is not None else ""
        if norm_option(got) != want:
            return {"name": name, "status": "error", "detail": f"readback '{got}' is not '{option}'"}
        return {"name": name, "status": "filled", "detail": got}

    def _country(self, entry, country):
        """The phone widget's Country react-select (input#country). Its options
        read '<Country> +<dial>' and the chosen value shows only '+<dial>'
        (seen live 2026-08-29), so the match is on the country-name part and
        the readback is checked against that option's dial code. No selector on
        the form: nothing to do. Country not offered: an error, never a guess."""
        inp = self._one(f"{self.FORM} input#country[role=combobox]")
        if inp is None:
            return entry
        want = norm_option(country)
        try:
            inp.click()
            inp.fill(country)
            listbox = "#react-select-country-listbox [role=option]"
            self.page.wait_for_selector(listbox, timeout=10000)
            opts = self.page.locator(listbox)
            target, dial = None, ""
            for i in range(opts.count()):
                text = opts.nth(i).inner_text().strip()
                m = re.match(r"^(.*?)\s*(\+\d+)?$", text)
                if m and norm_option(m.group(1)) == want:
                    target, dial = opts.nth(i), (m.group(2) or "")
                    break
            if target is None:
                self.page.keyboard.press("Escape")
                return {"name": entry["name"], "status": "option_not_found", "detail": f"country '{country}' not offered"}
            target.click()
            chosen = self._one("xpath=//input[@id='country']/ancestor::div[contains(@class,'select__value-container')]"
                               "//div[contains(@class,'select__single-value')]")
            got = (chosen.inner_text().strip() if chosen is not None else "")
            ok = norm_option(got) in (norm_option(dial), norm_option(f"{country} {dial}"), want) and got != ""
            if not ok:
                return {"name": entry["name"], "status": "error", "detail": f"country readback '{got}' is not '{country}' / '{dial}'"}
            entry["detail"] = (entry["detail"] + " " if entry["detail"] else "") + f"country={country}"
            return entry
        except Exception as e:
            return {"name": entry["name"], "status": "error", "detail": f"country: {type(e).__name__}: {e}"[:120]}

    def submit(self):
        self.page.locator(f"{self.FORM} button[type=submit]").first.click()

    def outcome(self, timeout_s):
        import time as _t
        deadline = _t.monotonic() + max(5, timeout_s)
        while _t.monotonic() < deadline:
            if self.challenge_visible():
                return "challenge", "an interactive challenge rendered after the click"
            text = self.page_text()
            url = self.page.url
            m = CONFIRM_RX.search(text)
            if m or "/confirmation" in url:
                return "confirmed", (m.group(0) if m else "confirmation page")
            try:
                alerts = self.page.locator("[role=alert]")
                for i in range(alerts.count()):
                    if alerts.nth(i).is_visible() and alerts.nth(i).inner_text().strip():
                        return "error", alerts.nth(i).inner_text().strip()[:200]
            except Exception:
                pass
            m = ERROR_RX.search(text)
            if m:
                return "error", m.group(0)
            _t.sleep(0.5)
        return "unknown", ""


DRIVERS = {"greenhouse": GreenhouseForm}


def driver_for(platform, cfg, allowed_hosts=ALLOWED_HOSTS):
    cls = DRIVERS.get(platform)
    if cls is None:
        raise Blocked("no_driver", f"no driver for {platform}")
    return cls(cfg, allowed_hosts=allowed_hosts)


def attempt(conn, run, row, packet, state, *, live, shot_dir, cfg=None, gap_sink=None):
    """submission.process() entry point: identity is loaded lazily (after the
    gates), the letter comes from the tracker row, the driver from the
    packet's platform."""
    cfg = cfg if cfg is not None else ACFG
    letter = (db.BASE_DIR / row["cover_letter_path"]) if row["cover_letter_path"] else None
    return run_head(conn, run, row, packet, ident=None, cfg=cfg, state=state,
                    driver_factory=lambda c: driver_for(packet.get("platform"), c),
                    live=live, shot_dir=shot_dir, letter_path=letter, gap_sink=gap_sink)
