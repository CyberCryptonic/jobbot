"""Layer 6 — submission (the 8 AM 'submission' stage).

Two paths, decided by apply_route:

  ats / direct  → a SUBMISSION PACKET: platform, the application form as far
                  as it can be read without logging in (Greenhouse publishes
                  it; Lever's apply page lists it; Ashby/Workday need an
                  account, so 'unknown'), every field mapped to the answer
                  bank with the section it came from, attachments (resume
                  byte-for-byte, letter when the form has a field for it), and
                  a decision: ready / skip (answer file §L rule 3) / hold.
  native        → nothing here; the Manual Queue (dashboard) serves it.

DRY RUN (config.json → submission.dry_run = true, the default): every packet
is built, written to submissions/YYYY-MM-DD/{id}.json, a form record PDF is
captured to screenshots/, and a 'submit_dryrun' row is logged with the whole
packet. Status never changes. Nothing contacts Jobright.

The Jobright finding (2026-08-29): Jobright's autofill is a Chrome extension
in the operator's browser and its Agent runs inside Jobright's app. Neither
has an API, an import URL, or a deep link a cron job can call. So the "live"
adapter here is a HANDOFF: the packet is surfaced on the dashboard's Agent
lane and the extension fills the form when the operator opens the job. See
JobrightHandoff below. Nothing in this file scripts a browser or a captcha.

Signal back to Layer 5: applications.letter_required (1 = the form has a
cover-letter field, 0 = it has none, NULL = unknown) + form_probed_at.
materials.py can skip letters for letter_required = 0 once the operator asks
for that (deferred, session 3).

The autonomous head (session 9, autosubmit.py): when config.json ->
submission.auto_submit.enabled is true, a READY packet on a supported ATS is
filled by Playwright; with auto_submit.dry_run true it is screenshotted and
then handed off exactly as before; live, it is submitted and the row becomes
'applied'. The first verify_first_n sends are screenshotted for the nightly
report — verification, not a gate (operator cleared the self-stop ramp
2026-09-01; --reviewed remains only to clear a stale/manual hold flag).

Run:  ./venv/bin/python pipeline/submission.py            # build packets for queued ats/direct rows
      ./venv/bin/python pipeline/submission.py --ids 108,194
      ./venv/bin/python pipeline/submission.py --dry-run --autosubmit --ids 167   # fill + screenshot, nothing sent, nothing changed
      ./venv/bin/python pipeline/submission.py --reviewed       # clear a stale/manually-set awaiting_review hold
      ./venv/bin/python pipeline/submission.py --reset-dryrun   # un-hide manual-queue cards marked in dry run
"""

import hashlib
import html
import json
import re
import sys
import time
from datetime import datetime
from pathlib import Path

import answers
import autosubmit
import db
from sources import common

CONFIG = json.loads((db.BASE_DIR / "config.json").read_text())
SCFG = CONFIG.get("submission", {})
DRY_RUN = SCFG.get("dry_run", True)
VERIFY_N = SCFG.get("verify_first_n", 20)
MAX_PER_RUN = SCFG.get("max_per_run", 25)
AUTO = dict(SCFG.get("auto_submit") or {})    # the autonomous ATS head's own gates (autosubmit.py); enabled=false by default
RESUME = db.RESUME_PATH
SUB_DIR = db.BASE_DIR / "submissions"
SHOT_DIR = db.BASE_DIR / "screenshots"

PLATFORMS = [
    ("greenhouse", re.compile(r"greenhouse\.io", re.I)),
    ("lever", re.compile(r"jobs\.lever\.co", re.I)),
    ("ashby", re.compile(r"ashbyhq\.com", re.I)),
    ("workday", re.compile(r"myworkdayjobs\.com", re.I)),
    ("oracle", re.compile(r"oraclecloud\.com", re.I)),
    ("statejobsny", re.compile(r"statejobs\.ny\.gov|statejobsny", re.I)),
    ("smartrecruiters", re.compile(r"smartrecruiters\.com", re.I)),
    ("icims", re.compile(r"icims\.com", re.I)),
    ("workable", re.compile(r"workable\.com", re.I)),
]


def platform_of(url):
    for name, rx in PLATFORMS:
        if rx.search(url or ""):
            return name
    return "direct"


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _rel(path):
    """Project-relative path for logs and the tracker; absolute when outside."""
    try:
        return str(Path(path).relative_to(db.BASE_DIR))
    except ValueError:
        return str(path)


# ---------------------------------------------------------------------------
# Form probes — read-only, unauthenticated, one request per job
# ---------------------------------------------------------------------------

def probe_greenhouse(url):
    m = re.search(r"greenhouse\.io/([^/]+)/jobs/(\d+)", url)
    if not m:
        return None
    board, jid = m.group(1), m.group(2)
    st, body, _ = common.http(
        f"https://boards-api.greenhouse.io/v1/boards/{board}/jobs/{jid}?questions=true", timeout=20)
    if st != 200:
        return {"platform": "greenhouse", "status": f"http {st}", "fields": None}
    j = json.loads(body)
    fields = []
    for q in j.get("questions", []):
        kinds = [f.get("type") for f in q.get("fields", [])]
        opts, inputs = [], []
        for f in q.get("fields", []):
            vals = [v.get("label") for v in (f.get("values") or [])]
            opts += vals[:8]
            inputs.append({"name": f.get("name"), "type": f.get("type"), "values": vals})
        fields.append({"label": q.get("label", ""), "required": bool(q.get("required")),
                       "kind": ",".join(kinds), "options": opts, "inputs": inputs})
    eeoc = 0
    for sec in j.get("compliance") or []:
        for q in sec.get("questions", []):
            eeoc += 1
            kinds = [f.get("type") for f in q.get("fields", [])]
            opts, inputs = [], []
            for f in q.get("fields", []):
                vals = [v.get("label") for v in (f.get("values") or [])]
                opts += vals[:8]
                inputs.append({"name": f.get("name"), "type": f.get("type"), "values": vals})
            fields.append({"label": q.get("label", ""), "required": bool(q.get("required")),
                           "kind": ",".join(kinds), "options": opts, "demographic": True,
                           "inputs": inputs})
    return {"platform": "greenhouse", "status": "read", "fields": fields,
            "eeoc_questions": eeoc, "apply_url": j.get("absolute_url"),
            "deadline": j.get("application_deadline"),
            # the job-board UI runs invisible reCAPTCHA at submit (verified 2026-08-29). Not a
            # door by itself: the head submits through it and stops the moment a challenge renders.
            "captcha_note": "invisible reCAPTCHA at submit; an interactive challenge routes to manual"}


LEVER_TOP = [  # (label as Lever shows it, input name, kind) — included only when the page has the input
    ("Resume/CV", "resume", "input_file"),
    ("Full name", "name", "input_text"),
    ("Email", "email", "input_text"),
    ("Phone", "phone", "input_text"),
    ("Current location", "location", "input_text"),
    ("Current company", "org", "input_text"),
    ("LinkedIn URL", "urls[LinkedIn]", "input_text"),
    ("GitHub URL", "urls[GitHub]", "input_text"),
    ("Portfolio URL", "urls[Portfolio]", "input_text"),
    ("Twitter URL", "urls[Twitter]", "input_text"),
    ("Other website", "urls[Other]", "input_text"),
]
LEVER_KIND = {"text": "input_text", "textarea": "textarea", "dropdown": "select",
              "multiple-choice": "radio", "multiple-select": "checkbox", "file": "input_file"}


def probe_lever(url):
    """Lever's apply page carries every question card as JSON in a hidden
    cards[<id>][baseTemplate] input (type, text, required, options); the
    inputs are named cards[<id>][field<N>]. Top-level identity inputs are
    plain HTML. Read-only, one GET."""
    m = re.search(r"jobs\.lever\.co/([^/]+)/([0-9a-f-]{36})", url)
    if not m:
        return None
    apply_url = f"https://jobs.lever.co/{m.group(1)}/{m.group(2)}/apply"
    st, body, _ = common.http(apply_url, timeout=20)
    if st != 200:
        return {"platform": "lever", "status": f"http {st}", "fields": None, "apply_url": apply_url}
    t = body.decode("utf8", "ignore")
    # required marks from the visible labels (✱), as Lever renders them
    starred = set()
    for lab in re.findall(r'<div class="application-label[^"]*">(.*?)</div>', t, re.S):
        txt = " ".join(html.unescape(re.sub(r"<[^>]+>", " ", lab)).split())
        if "✱" in txt:
            starred.add(txt.replace("✱", "").strip().lower())
    fields = []
    for label, name, kind in LEVER_TOP:
        tag = re.search(r'<input[^>]*\bname="%s"[^>]*>' % re.escape(name), t)
        if not tag:
            continue
        req = "required" in tag.group(0) or label.lower() in starred
        fields.append({"label": label, "required": req, "kind": kind, "options": [],
                       "inputs": [{"name": name, "type": kind, "values": []}]})
    for m2 in re.finditer(r'<input type="hidden" value="([^"]*)"\s+name="cards\[([^\]]+)\]\[baseTemplate\]"', t):
        try:
            card = json.loads(html.unescape(m2.group(1)))
        except ValueError:
            continue
        for i, f in enumerate(card.get("fields") or []):
            kind = LEVER_KIND.get(f.get("type"), f.get("type") or "text")
            opts = [o.get("text") for o in (f.get("options") or []) if o.get("text")]
            fields.append({"label": " ".join(str(f.get("text", "")).split()), "required": bool(f.get("required")),
                           "kind": kind, "options": opts[:8] if kind not in ("select", "radio", "checkbox") else opts,
                           "inputs": [{"name": f"cards[{m2.group(2)}][field{i}]", "type": kind, "values": opts}]})
    if 'name="comments"' in t:
        fields.append({"label": "Additional information", "required": False, "kind": "textarea", "options": [],
                       "inputs": [{"name": "comments", "type": "textarea", "values": []}]})
    return {"platform": "lever", "status": "read", "fields": fields,
            "captcha": "h-captcha-response" in t, "apply_url": apply_url}


ASHBY_QUERY = ("query ApiJobPosting($organizationHostedJobsPageName: String!, $jobPostingId: String!) { "
               "jobPosting(organizationHostedJobsPageName: $organizationHostedJobsPageName, jobPostingId: $jobPostingId) { "
               "id title applicationForm { sections { title fieldEntries { isRequired isHidden field } } } } }")
ASHBY_KIND = {"String": "input_text", "Email": "input_text", "Phone": "input_text", "LongText": "textarea",
              "File": "input_file", "Boolean": "boolean", "ValueSelect": "select", "Location": "location",
              "Number": "input_text", "Date": "input_text", "MultiValueSelect": "checkbox"}


def probe_ashby(url):
    """The same public GraphQL query the Ashby application page makes
    (verified read-only 2026-08-29): the form schema with paths, types,
    required flags and selectable values. The page runs invisible reCAPTCHA."""
    m = re.search(r"jobs\.ashbyhq\.com/([^/]+)/([0-9a-f-]{36})", url)
    if not m:
        return None
    org, jid = m.group(1), m.group(2)
    apply_url = f"https://jobs.ashbyhq.com/{org}/{jid}/application"
    st, body, _ = common.http(
        "https://jobs.ashbyhq.com/api/non-user-graphql?op=ApiJobPosting", method="POST", timeout=20,
        body={"operationName": "ApiJobPosting", "query": ASHBY_QUERY,
              "variables": {"organizationHostedJobsPageName": org, "jobPostingId": jid}},
        headers={"apollographql-client-name": "frontend_non_user"})
    if st != 200:
        return {"platform": "ashby", "status": f"http {st}", "fields": None, "apply_url": apply_url}
    try:
        jp = json.loads(body)["data"]["jobPosting"]
        sections = (jp.get("applicationForm") or {}).get("sections") or []
    except (ValueError, KeyError, TypeError):
        return {"platform": "ashby", "status": "unreadable", "fields": None, "apply_url": apply_url}
    fields = []
    for sec in sections:
        for fe in sec.get("fieldEntries") or []:
            if fe.get("isHidden"):
                continue
            f = fe.get("field") or {}
            kind = ASHBY_KIND.get(f.get("type"), (f.get("type") or "text").lower())
            opts = [v.get("label") for v in (f.get("selectableValues") or []) if v.get("label")]
            if kind == "boolean":
                opts = ["Yes", "No"]
            fields.append({"label": " ".join(str(f.get("title", "")).split()), "required": bool(fe.get("isRequired")),
                           "kind": kind, "options": opts,
                           "inputs": [{"name": f.get("path"), "type": kind, "values": opts}]})
    return {"platform": "ashby", "status": "read", "fields": fields, "captcha": False,
            "apply_url": apply_url, "title": jp.get("title"),
            "captcha_note": "invisible reCAPTCHA at submit; an interactive challenge routes to manual"}


def probe_form(url):
    p = platform_of(url)
    if p == "greenhouse":
        return probe_greenhouse(url)
    if p == "lever":
        return probe_lever(url)
    if p == "ashby":
        return probe_ashby(url)
    note = {"ashby": "Ashby form schema unreadable",
            "workday": "Workday questionnaires require a candidate account; form visible only at apply time",
            "oracle": "Oracle Recruiting apply flow requires an account",
            "direct": "company site; no structured form API"}.get(p, "no probe for this platform")
    return {"platform": p, "status": "unknown", "fields": None, "note": note}


# ---------------------------------------------------------------------------
# Field mapping — every fill traces to the answer file, to identity.json (the
# autonomous head's only identity source), or to Jobright autofill, which
# completes profile fields in the operator's browser on manual handoff packets
# ---------------------------------------------------------------------------

PROFILE = "identity block (identity.json for the autonomous head; Jobright autofill on manual handoff)"

RULES = [  # (label regex, kind, section, field-or-literal) — first match wins
    (r"share something|in your own words|tell us about|describe (a|your)|proudest|favorite project|essay", "essay", None, None),
    (r"^(first name|last name|full name|name)$|legal name|^email$|^phone$|current company|current location|^location$", "profile", None, None),
    (r"linkedin|github|portfolio|personal website|website or blog", "profile", None, None),
    (r"pronunciation|pronounce", "optional_blank", None, None),
    (r"^(resume|cv)\b|resume/cv|upload .*(resume|cv)|attach .*(resume|cv)", "attach_resume", None, None),
    (r"cover letter", "attach_letter", None, None),
    (r"additional information", "letter_text", None, None),
    (r"how did you hear|hear about|how you heard|heard about", "source", "H", "How did you hear about this position"),
    (r"ever been employed by|history with|previously (worked|employed)|former employee|worked (at|for) .* before", "answer", "E", "Previously employed here"),
    (r"export control|u\.?s\.? person|us person|citizen|protected individual", "answer", "F", "Export controls / U.S. person status"),
    (r"held a .*clearance|clearance in the past|previous(ly)? .*clearance", "answer", "F", "Clearance level held in the past"),
    (r"based in (singapore|tokyo|london|europe|the uk)|currently (based|located) in", "attest", "C", "Current location"),
    (r"sponsorship|work authoriz|legally authorized|authorized to work|authorization to work", "answer", "ID", "Work authorization"),
    (r"relocat|willing to (move|relocate)|live in|currently live", "answer", "C", "Willing to relocate"),
    (r"active .*clearance|hold .*clearance|current clearance|security clearance\?", "answer", "F", "Current clearance"),
    (r"eligible to obtain|obtain .*clearance|clearance eligib", "answer", "F", "Eligible"),
    (r"salary|compensation expect|desired pay", "answer", "A", '"Desired salary" when a single number is required'),
    (r"start date|when (can|could) you start|available to start", "answer", "B", "Earliest start date"),
    (r"preferred (first )?name|like us to call you", "answer", "H", "Preferred name"),
    (r"on-?site \d+ days|work out of the .* site|located in the|based in the", "attest", "C", "Willing to relocate"),
    (r"minimum .*years|years of .*experience|meet the .*experience", "attest", "D", "Years of professional IT experience"),
    (r"\bpronouns?\b", "answer", "H", "Pronouns"),
    (r"commute", "answer", "C", "Max one-way commute"),      # before on-call: "commute ... when on-call" is a location question
    (r"on-call|on call|shift|weekend|night", "answer", "B", "Weekends or on-call rotation"),
    (r"travel", "answer", "B", "Maximum travel"),
    (r"university|school|degree|education|attend", "profile", None, None),
    (r"certif", "answer", "E", "Certifications in progress"),
    (r"18 (years|or older)|over 18|age of 18", "answer", "E", "18 or older"),
    (r"felony|convict", "answer", "E", "Convicted of a felony"),
    (r"non-?compete", "answer", "E", "Subject to a non-compete"),
    (r"related to|relative", "answer", "E", "Related to a current employee"),
    (r"background check", "answer", "E", "Background check"),
    (r"drug", "answer", "E", "Drug screen"),
    (r"privacy|acknowledg|consent|agree to|terms", "acknowledge", None, None),
    (r"language skill|languages? (you )?speak|bilingual|fluent in", "answer", "E", "Language skills"),
    (r"conflict of interest", "answer", "E", "Conflict of interest"),
]

ATTESTATION_RX = re.compile(r"salary|compensation|years of|experience|clearance|felony|convict|criminal|authoriz|sponsorship|degree|education", re.I)


# Voluntary EEO self-identification (operator, 2026-08-31): decline every
# self-ID question, in the form's own decline wording. The label match is
# deliberately anchored so accommodation or eligibility questions never land
# here; probe-flagged fields (demographic=True) match regardless of label.
DEMOGRAPHIC_RX = re.compile(
    r"^(gender|gender identity|race|ethnicity|race/ethnicity|race ethnicity)$"
    r"|^veteran ?status$|^disability ?status$"
    r"|^(are you )?hispanic/? ?latino\??$", re.I)
SELF_ID_ROWS = [
    (re.compile(r"gender", re.I), "Gender self-identification"),
    (re.compile(r"race|ethnic|hispanic|latino", re.I), "Race / ethnicity self-identification"),
    (re.compile(r"veteran", re.I), "Veteran status self-identification"),
    (re.compile(r"disab", re.I), "Disability status self-identification"),
]
DECLINE_NORM = {autosubmit.norm_option(p) for p in (
    "Decline To Self Identify", "Decline to self-identify", "I don't wish to answer",
    "I do not wish to answer", "I don't want to answer", "I do not want to answer",
    "Prefer not to say", "Prefer not to answer", "Prefer not to disclose",
    "Decline to answer", "Decline to state", "I prefer not to say")}


def self_id_decline(f, bank):
    """The fill decision for a voluntary self-ID question, or None when the
    field is not one. Never a gap: these are voluntary, so a question with no
    stored answer or no matching option is simply left blank."""
    lab = " ".join(f["label"].split()).rstrip("*").strip()
    if not (f.get("demographic") or DEMOGRAPHIC_RX.match(lab)):
        return None
    stored = None
    for rx, key in SELF_ID_ROWS:
        if rx.search(lab):
            stored = answers.get(bank, "ID", key)
            break
    if stored is None:
        return {"fill": "blank", "value": "", "demographic": True,
                "source": "voluntary self-ID with no Identity/EEO answer; left blank"}
    opts = []
    for inp in f.get("inputs") or []:
        opts += [o for o in (inp.get("values") or []) if o]
    opts = opts or list(f.get("options") or [])
    if autosubmit.norm_option(stored) in DECLINE_NORM:
        hit = next((o for o in opts if autosubmit.norm_option(o) in DECLINE_NORM), None)
        if hit:
            return {"fill": "value", "value": hit, "demographic": True,
                    "source": "answer file, Identity/EEO block: decline to self-identify (form's own wording)"}
        return {"fill": "blank", "value": "", "demographic": True,
                "source": "answer file, Identity/EEO block: decline to self-identify; this form offers no decline option, left blank"}
    return {"fill": "value", "value": stored, "demographic": True,
            "source": "answer file, Identity/EEO block"}


SITE_WORDS = re.compile(r"website|web site|careers? (page|site)|jobs? (site|page|board)|company site|\.com\b|\.org\b", re.I)
BOARD_OPTION = {"indeed_alert": "indeed", "linkedin": "linkedin", "glassdoor_alert": "glassdoor",
                "ziprecruiter_alert": "ziprecruiter", "jobright_alert": "jobright"}


def hear_option(row, f):
    """Operator rule 2026-08-29 for 'how did you hear' dropdowns: found on the
    company's own site -> the '[Company] Website'-style option; found on a
    board -> that board's option. None when the list offers neither (the
    generic answer stays and the head treats it as a gap)."""
    opts = []
    for inp in f.get("inputs") or []:
        opts += [o for o in (inp.get("values") or []) if o]
    opts = opts or list(f.get("options") or [])
    if not opts:
        return None
    src = row["source"] or ""
    if src == "company_page":
        words = [w for w in re.findall(r"[a-z0-9]+", (row["company"] or "").lower())
                 if w not in ("inc", "llc", "ltd", "corp", "corporation", "co", "the", "industries", "technologies", "group")]
        for o in opts:
            low = o.lower()
            if SITE_WORDS.search(low) and (not words or any(w in low for w in words)):
                return o
        return None
    board = BOARD_OPTION.get(src)
    if board:
        for o in opts:
            if board in o.lower():
                return o
    return None


# The §ID authorization line answers US employment only. A sponsorship or
# authorization question scoped to any other place must come from the bank
# explicitly (like the operator's Singapore answer) or become a gap — never a
# defaulted attestation. Live miss this guarded against: a foreign-scoped Japan
# sponsorship question auto-answered "No" from the US default (2026-09-01).
US_PLACES = {"us", "u.s", "usa", "u.s.a", "united states", "the united states",
             "the us", "the u.s", "the usa", "america", "united states of america",
             "the united states of america"}
NON_PLACE_IN = ("the future", "the past", "the meantime", "the near", "this ", "that ",
                "your ", "a ", "an ", "order", "addition", "accordance", "general",
                "writing", "advance", "person", "part", "full", "time", "any capacity")


def _auth_place(low):
    """The place an authorization question is scoped to ('in X'), or None."""
    for m in re.finditer(r"\bin ((?:the )?[a-z][a-z. ]{0,30}?)(?=[?,;:!)]|$| and\b| or\b)", low):
        place = m.group(1).strip()
        if any(place.startswith(x) for x in NON_PLACE_IN):
            continue
        return place
    return None


def _auth_scope(low):
    place = _auth_place(low)
    if place is None:
        return "generic", None
    return ("us", place) if place.rstrip(".") in US_PLACES else ("foreign", place)


def map_field(f, row, bank, letter_meta):
    """Return the fill decision for one form field, per answer file §L."""
    label = f["label"]
    low = label.lower()
    d = self_id_decline(f, bank)
    if d is not None:
        return d
    # a question the answer file holds under this exact wording (chat gap
    # answers land here) wins over the pattern rules below
    val, sec = answers.find_by_label(bank, label)
    if val is not None:
        return {"fill": "text" if len(val) > 120 else "value", "value": val, "source": f"answer file §{sec} (matched the form's own question)"}
    for rx, kind, sec, field in RULES:
        if re.search(rx, low):
            if kind == "profile":
                return {"fill": "autofill", "value": PROFILE,
                        "source": "identity: identity.json (head) / Jobright autofill (handoff)"}
            if kind == "attach_resume":
                return {"fill": "attach", "value": RESUME.name, "source": "resume, unmodified"}
            if kind == "attach_letter":
                return {"fill": "attach" if row["cover_letter_path"] else "blank",
                        "value": Path(row["cover_letter_path"]).name if row["cover_letter_path"] else "(no letter yet; materials writes 25/day)",
                        "source": "letters/ (Layer 5)", "letter_field": True}
            if kind == "letter_text":
                return {"fill": "text" if row["cover_letter_path"] else "blank",
                        "value": "cover letter text (.txt twin)" if row["cover_letter_path"] else "(no letter yet)",
                        "source": "letters/ (Layer 5)", "letter_field": True}
            if kind == "source":
                from materials import BOARD_NAME
                generic = BOARD_NAME.get(row["source"], "Company website")
                pick = hear_option(row, f)
                if pick:
                    return {"fill": "value", "value": pick, "source": "answer file §H (dropdown rule: the option for where discovery found it)"}
                return {"fill": "value", "value": generic, "source": "answer file §H"}
            if kind == "attest":
                val = answers.get(bank, sec, field)
                return {"fill": "value", "value": val, "source": f"answer file §{sec} (inferred from '{field}'; logged)",
                        "inferred": True}
            if kind == "acknowledge":
                return {"fill": "value", "value": "Yes / acknowledged", "source": "§L rule 2 (inferred; logged)",
                        "inferred": True}
            if kind == "essay":
                if f["required"]:
                    return {"fill": "GAP", "value": "", "source": "free-text essay; answer file §L rule 3"}
                return {"fill": "blank", "value": "", "source": "§L rule 1 (optional essay, left blank)"}
            if kind == "optional_blank":
                return {"fill": "blank", "value": "", "source": "§L rule 1 (optional, left blank)"}
            if kind == "gap":
                return {"fill": "GAP", "value": "", "source": field}
            if kind == "answer":
                if field == "Previously employed here":
                    val, src = answers.previously_employed(bank, row["company"])
                    return {"fill": "value", "value": val, "source": src}
                val = answers.get(bank, sec, field)
                if val is None:
                    return {"fill": "GAP", "value": "", "source": f"answer file §{sec} has no '{field}'"}
                # yes/no forms of the authorization line (answer file top block)
                if sec == "ID":
                    scope, place = _auth_scope(low)
                    if scope == "foreign":
                        return {"fill": "GAP", "value": "",
                                "source": f"scoped to {place} — §ID answers US employment only; needs its own bank answer"}
                    if "sponsor" in low:
                        return {"fill": "value", "value": "No", "source": "answer file §ID (no sponsorship required — US)"}
                    if "authoriz" in low:
                        return {"fill": "value", "value": "Yes", "source": "answer file §ID (authorized to work in the US)"}
                return {"fill": "value", "value": val, "source": f"answer file §{sec}"}
    # free text the file does not cover
    if re.search(r"why .*(interested|apply|join)|interest in", low) and letter_meta.get("why"):
        return {"fill": "text", "value": letter_meta["why"], "source": "WHY line generated with the letter"}
    if f["required"]:
        return {"fill": "GAP", "value": "", "source": "not covered by the answer file"}
    return {"fill": "blank", "value": "", "source": "§L rule 1 (optional, left blank)"}


# ---------------------------------------------------------------------------
# Packets
# ---------------------------------------------------------------------------

def build_packet(conn, row, bank, run):
    url = row["job_url"] or ""
    plat = platform_of(url)
    form = probe_form(url) if SCFG.get("probe_forms", True) else {"platform": plat, "status": "not probed", "fields": None}
    letter_meta = {}
    if row["cover_letter_path"]:
        mp = (db.BASE_DIR / row["cover_letter_path"]).with_suffix(".json")
        if mp.exists():
            try:
                letter_meta = json.loads(mp.read_text())
            except ValueError:
                pass
    fills, gaps, inferred = [], [], []
    letter_required = None
    if form.get("fields") is not None:
        letter_required = 0
        for f in form["fields"]:
            d = map_field(f, row, bank, letter_meta)
            if d.get("letter_field"):
                letter_required = 1
            if d["fill"] == "GAP":
                gaps.append((f, d))
            if d.get("inferred"):
                inferred.append(f["label"])
            fills.append({"label": f["label"], "required": f["required"], "kind": f["kind"],
                          "inputs": f.get("inputs") or [], **d})
    # decision per §L
    blocking = [(f, d) for f, d in gaps if f["required"]]
    if blocking:
        decision, why = "skip", ("required question the answer file cannot answer: "
                                 + "; ".join(f["label"][:60] for f, _ in blocking))
    elif form.get("captcha"):
        decision, why = "handoff", "form has a captcha; Jobright autofill in the operator's browser completes it"
    elif form.get("fields") is None:
        decision, why = "handoff", f"form not readable ahead of time ({form.get('status')}); Jobright autofill reads it live"
    else:
        decision, why = "ready", "every required field maps to the answer file, the profile, or an attachment"
    attachments = [{"file": RESUME.name, "sha256": sha256(RESUME), "role": "resume (byte-for-byte)"}]
    if row["cover_letter_path"] and (letter_required in (1, None)):
        lp = db.BASE_DIR / row["cover_letter_path"]
        if lp.exists():
            attachments.append({"file": lp.name, "sha256": sha256(lp),
                                "role": "cover letter" + ("" if letter_required == 1 else " (form unknown; attach if asked)")})
    packet = {
        "application_id": row["id"], "company": row["company"], "role": row["role"],
        "location": row["location"], "fit_score": row["fit_score"], "tier": row["tier"],
        "apply_route": row["apply_route"], "platform": form.get("platform", plat),
        "job_url": url, "apply_url": form.get("apply_url") or url,
        "form_status": form.get("status"), "form_note": form.get("note"),
        "captcha": bool(form.get("captcha")), "captcha_note": form.get("captcha_note"),
        "eeoc_questions": form.get("eeoc_questions"),
        "fields": fills, "attachments": attachments,
        "screening_answers": json.loads(row["screening_answers"] or "[]"),
        "letter_required": letter_required, "inferred_answers": inferred,
        "gaps": [f["label"] for f, _ in gaps],
        "decision": decision, "decision_reason": why,
        "mode": "DRY RUN" if DRY_RUN else "LIVE", "built": db.now(),
    }
    return packet


def form_record_pdf(packet, path):
    """The 'screenshot' for the verification window: a one-page record of
    exactly what would be filled and attached."""
    from reportlab.lib.pagesizes import letter
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.units import inch
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
    from reportlab.lib import colors
    esc = lambda s: str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    h = ParagraphStyle("h", fontName="Helvetica-Bold", fontSize=12, leading=15)
    b = ParagraphStyle("b", fontName="Helvetica", fontSize=8.5, leading=11)
    doc = SimpleDocTemplate(str(path), pagesize=letter, leftMargin=0.6 * inch, rightMargin=0.6 * inch,
                            topMargin=0.6 * inch, bottomMargin=0.6 * inch)
    flow = [Paragraph(esc(f"{packet['mode']} · form record · {packet['company']} — {packet['role']}"), h),
            Paragraph(esc(f"#{packet['application_id']} · {packet['platform']} · {packet['apply_url']}"), b),
            Paragraph(esc(f"decision: {packet['decision']} — {packet['decision_reason']}"), b),
            Spacer(1, 8)]
    rows = [["Field", "Req", "Fill", "Value", "Source"]]
    for f in packet["fields"] or []:
        rows.append([Paragraph(esc(f["label"][:80]), b), "✱" if f["required"] else "",
                     f["fill"], Paragraph(esc(str(f["value"])[:120]), b), Paragraph(esc(f["source"]), b)])
    if len(rows) == 1:
        rows.append([Paragraph(esc(packet.get("form_note") or "form not readable"), b), "", "", "", ""])
    for a in packet["attachments"]:
        rows.append([Paragraph(esc(a["role"]), b), "", "attach", Paragraph(esc(a["file"]), b),
                     Paragraph(esc("sha256 " + a["sha256"][:16] + "…"), b)])
    t = Table(rows, colWidths=[2.1 * inch, 0.35 * inch, 0.6 * inch, 2.4 * inch, 1.85 * inch], repeatRows=1)
    t.setStyle(TableStyle([("FONT", (0, 0), (-1, 0), "Helvetica-Bold", 8.5),
                           ("FONT", (0, 1), (-1, -1), "Helvetica", 8.5),
                           ("GRID", (0, 0), (-1, -1), 0.3, colors.grey),
                           ("VALIGN", (0, 0), (-1, -1), "TOP")]))
    flow.append(t)
    doc.build(flow)


class JobrightHandoff:
    """The 'live' adapter. There is no Jobright API; live mode surfaces the
    packet on the dashboard Agent lane and records the handoff. Anything
    beyond that (a real API, an import endpoint) plugs in here."""

    def submit(self, conn, run, row, packet):
        if DRY_RUN:
            raise RuntimeError("submit() called in dry run")
        db.set_status(conn, row["id"], "queued", next_action="AGENT-HANDOFF: open in browser, Jobright autofill completes the form",
                      append_note="handed to Jobright autofill via dashboard Agent lane")
        run.log("submit_handoff", subject=f"{row['company']} — {row['role']}",
                application_id=row["id"], reason=packet["decision_reason"][:300],
                detail=json.dumps(packet))


def process(run, conn, rows):
    bank = answers.load()
    state = common.load_state()
    # retired 2026-08-31 (operator): handoff form records no longer count toward
    # the verification window; only the head's actual submit_click sends do
    # (state.auto_submit.live_count). The old handoff counter is dropped on sight.
    state.setdefault("submission", {}).pop("verified", None)
    window_n = int(AUTO.get("verify_first_n", VERIFY_N) or 0)
    day_dir = SUB_DIR / db.today()
    shot_dir = SHOT_DIR / db.today()
    counts = {"ready": 0, "skip": 0, "handoff": 0}
    auto = state.setdefault("auto_submit", {})
    auto["live_this_run"] = 0
    head_live = bool(AUTO.get("enabled")) and not DRY_RUN and not AUTO.get("dry_run", True)
    gap_questions = []       # driveable jobs the head could not finish for lack of an answer
    for row in rows:
        if db.kill_switch():
            run.log("kill_switch_stop", outcome="skip",
                    reason=f"PAUSE file appeared mid-batch; stopped before {row['company']} — {row['role']}")
            break
        subject = f"{row['company']} — {row['role']}"
        t0 = time.monotonic()
        try:
            packet = build_packet(conn, row, bank, run)
        except Exception as e:
            run.log("submit_packet", subject=subject, application_id=row["id"], outcome="fail",
                    reason=f"packet build failed: {type(e).__name__}: {e}"[:250])
            continue
        day_dir.mkdir(parents=True, exist_ok=True)
        ppath = day_dir / f"{row['id']}.json"
        ppath.write_text(json.dumps(packet, indent=1))
        rel = _rel(ppath)
        conn.execute("UPDATE applications SET letter_required=?, form_probed_at=?, submission_path=? WHERE id=?",
                     (packet["letter_required"], db.now() if packet["fields"] else None, rel, row["id"]))
        for g in packet["gaps"]:
            db.upsert_answer_gap(conn, f"{g} (form field, {packet['platform']})", application_id=row["id"])
            run.log("answer_gap", subject=subject, application_id=row["id"], outcome="warn",
                    reason=f"form asks: {g}"[:250])
        for lab in packet["inferred_answers"]:
            run.log("answer_inferred", subject=subject, application_id=row["id"],
                    reason=f"§L rule 2: acknowledged '{lab[:80]}'")
        counts[packet["decision"]] += 1
        dur = int((time.monotonic() - t0) * 1000)
        # capture window: handoff form records while the head is still inside
        # its verify_first_n live sends (submit_click count); in dry run every
        # packet gets one so the operator can review the chain
        capture = DRY_RUN or (window_n and int(auto.get("live_count", 0)) < window_n)
        shot = None
        if capture and packet["decision"] != "skip":
            shot_dir.mkdir(parents=True, exist_ok=True)
            shot = shot_dir / f"{row['id']}-{re.sub(r'[^a-z0-9]+', '-', row['company'].lower())[:30]}.pdf"
            form_record_pdf(packet, shot)
        # the autonomous head (autosubmit.py): READY packets on a supported ATS.
        # Only an actual send ('applied') or a click with no confirmation
        # ('unknown', CHECK note set) skips today's handoff; every other
        # outcome falls through to it exactly as before.
        if packet["decision"] == "ready" and AUTO.get("enabled"):
            outcome = autosubmit.attempt(conn, run, row, packet, state, live=head_live,
                                         shot_dir=shot_dir, cfg=AUTO, gap_sink=gap_questions)
            key = "auto_" + outcome.split(":")[0]
            counts[key] = counts.get(key, 0) + 1
            if outcome in ("applied", "unknown") or outcome == "refused:submit_click":
                # applied: done. unknown: CHECK note set, the operator/inbox
                # decides. refused:submit_click: a click already happened for
                # this row; never overwrite its note with a fresh handoff.
                common.save_state(state)
                continue
            if (row["next_action"] or "").startswith("AGENT-HANDOFF"):
                # already on the operator's Agent lane; the head only looked
                # (dry run / refused / blocked) — nothing to hand off again
                continue
        if DRY_RUN:
            run.log("submit_dryrun", subject=subject, application_id=row["id"],
                    outcome={"ready": "ok", "handoff": "ok", "skip": "skip"}[packet["decision"]],
                    duration_ms=dur, detail=json.dumps(packet),
                    reason=(f"[DRY RUN] {packet['decision'].upper()} via {packet['platform']}: "
                            f"{packet['decision_reason']} | attach {len(packet['attachments'])} "
                            f"| fields {len(packet['fields'])} | letter_required {packet['letter_required']}"
                            + (f" | record {shot.name}" if shot else ""))[:400])
            continue
        if packet["decision"] == "skip":
            db.set_status(conn, row["id"], "skipped", append_note="skipped: " + packet["decision_reason"])
            run.log("skip_job", subject=subject, application_id=row["id"], outcome="skip",
                    reason=packet["decision_reason"][:300], detail=json.dumps(packet))
            continue
        JobrightHandoff().submit(conn, run, row, packet)
        if shot:
            run.log("form_record", subject=subject, application_id=row["id"],
                    reason=f"handoff form record (head live sends {int(auto.get('live_count', 0))}/{window_n}): {_rel(shot)}")
    if gap_questions and not DRY_RUN:
        autosubmit.notify_gaps(run, gap_questions)
    common.save_state(state)
    return counts


def mark_reviewed(conn):
    """Operator acknowledgement for the head's verification window: clears the
    self-stop so the next run may send again. Logged."""
    state = common.load_state()
    st = state.setdefault("auto_submit", {})
    n = int(st.get("live_count", 0))
    st["awaiting_review"] = False
    st["reviewed_through"] = n
    st["reviewed_at"] = db.now()
    common.save_state(state)
    db.log("submission", "review_ack", run_id="manual-" + datetime.now(db.TZ).strftime("%Y%m%d-%H%M%S"),
           reason=f"operator reviewed auto-submit sends through #{n}; self-stop cleared", conn=conn)
    return n


def reset_dryrun(conn):
    n = conn.execute("UPDATE applications SET next_action=NULL WHERE next_action LIKE 'DRY-RUN%'").rowcount
    db.log("submission", "dryrun_reset", run_id="manual-" + datetime.now(db.TZ).strftime("%Y%m%d-%H%M%S"),
           reason=f"{n} manual-queue cards un-hidden", conn=conn)
    return n


def select_rows(conn, ids=None, limit=None, head_enabled=None):
    """The morning batch: queued ats/direct rows. Rows the head clicked
    without seeing a confirmation (CHECK: …) always wait for the operator /
    the inbox. Rows already handed off (AGENT-HANDOFF) are skipped when the
    head is off (no re-handoff every morning) and included when it is on —
    a packet waiting on the operator is exactly what the head is for."""
    head_enabled = bool(AUTO.get("enabled")) if head_enabled is None else head_enabled
    q = ("SELECT * FROM applications WHERE status='queued' AND suspicious=0 "
         "AND apply_route IN ('ats','direct')")
    args = []
    if ids:
        q += f" AND id IN ({','.join('?' * len(ids))})"; args += list(ids)
    else:
        q += " AND (next_action IS NULL OR next_action NOT LIKE 'CHECK:%')"
        if not head_enabled:
            q += " AND (next_action IS NULL OR next_action NOT LIKE 'AGENT-HANDOFF%')"
    q += " ORDER BY fit_score DESC, id LIMIT ?"; args.append(limit or MAX_PER_RUN)
    return conn.execute(q, args).fetchall()


def main(argv):
    global DRY_RUN
    if db.halt_if_paused("submission"):
        return
    if "--dry-run" in argv:
        DRY_RUN = True          # one-off review run: log what would happen, change nothing
    if "--autosubmit" in argv:
        # one-off review of the head: force it on for this run, and force its
        # dry run — a command-line flag can never make it send
        AUTO["enabled"] = True
        AUTO["dry_run"] = True
    if "--reviewed" in argv:
        with db.connect() as conn:
            print("reviewed through live send #", mark_reviewed(conn))
        return
    if "--reset-dryrun" in argv:
        with db.connect() as conn:
            print("reset:", reset_dryrun(conn))
        return
    ids = [int(x) for x in argv[argv.index("--ids") + 1].split(",")] if "--ids" in argv else None
    limit = 10_000 if "--all" in argv else MAX_PER_RUN
    with db.Run("submission") as run:
        conn = run.conn
        rows = select_rows(conn, ids, limit)
        native = conn.execute("SELECT COUNT(*) c FROM applications WHERE status='queued' AND apply_route='native'").fetchone()["c"]
        pending = conn.execute("SELECT COUNT(*) c FROM applications WHERE status='queued' "
                               "AND next_action LIKE 'AGENT-HANDOFF%'").fetchone()["c"]
        counts = process(run, conn, rows)
        auto_note = ""
        if AUTO.get("enabled"):
            st = common.load_state().get("auto_submit", {})
            auto_note = (f"; auto-submit head {'DRY RUN' if (DRY_RUN or AUTO.get('dry_run', True)) else 'LIVE'}"
                         f" (live sends {st.get('live_count', 0)}/{AUTO.get('verify_first_n', 20)}"
                         + (", self-stopped awaiting review" if st.get("awaiting_review") else "") + ")")
        base = {k: v for k, v in counts.items() if not k.startswith("auto_")}
        run.log("stage_summary", outcome="warn" if DRY_RUN else "ok",
                reason=(f"{'DRY RUN — nothing submitted. ' if DRY_RUN else ''}"
                        f"ats/direct packets: {sum(base.values())} ({base}); "
                        f"manual queue holds {native} native cards"
                        + (f"; {pending} earlier handoff(s) still await the operator (not re-sent)" if pending else "")
                        + auto_note))
    print("submission done:", counts, "| dry_run =", DRY_RUN)


if __name__ == "__main__":
    main(sys.argv[1:])
