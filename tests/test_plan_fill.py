"""autosubmit.plan_fill — the deterministic mapping from a packet to concrete
form actions. Rules under test (plan §2, gates 3–6):
  - a select answer must equal one of the form's options (normalised exact match)
  - an inferred answer is never filled: it becomes an answer gap with the options quoted
  - attestation-class labels need an explicit answer-file source
  - identity fields come from identity.json, nothing else
  - attachments are verified against the packet's sha256
"""
import hashlib
import json
import os

import pytest

import autosubmit as A


def _field(label, fill, value="", *, required=True, source="answer file §E", name="question_1",
           ftype="multi_value_single_select", options=None, inferred=False, extra=None):
    f = {"label": label, "required": required, "kind": ftype, "fill": fill, "value": value,
         "source": source, "inputs": [{"name": name, "type": ftype, "values": options or []}]}
    if inferred:
        f["inferred"] = True
    if extra:
        f.update(extra)
    return f


@pytest.fixture
def identity():
    return {"first_name": "Alex", "last_name": "Rivera", "email": "applicant@example.org",
            "phone": "555-010-0100", "linkedin": "https://linkedin.com/in/x",
            "website": "https://example.org", "github": "https://github.com/x",
            "city": "Rivertown", "state": "NY", "country": "United States"}


@pytest.fixture
def files(tmp_path):
    resume = tmp_path / "resume.pdf"; resume.write_bytes(b"%PDF resume")
    letter = tmp_path / "letter.pdf"; letter.write_bytes(b"%PDF letter")
    return resume, letter


def _packet(fields, resume, letter=None):
    att = [{"file": resume.name, "sha256": hashlib.sha256(resume.read_bytes()).hexdigest(), "role": "resume (byte-for-byte)"}]
    if letter:
        att.append({"file": letter.name, "sha256": hashlib.sha256(letter.read_bytes()).hexdigest(), "role": "cover letter"})
    return {"application_id": 1, "company": "Meridian Dynamics", "role": "SOC", "platform": "greenhouse",
            "decision": "ready", "fields": fields, "attachments": att, "inferred_answers": [], "gaps": []}


# --- option matching ---------------------------------------------------------

def test_match_option_is_exact_after_normalisation():
    opts = ["Yes", "No", "N/A - have never held U.S. security clearance"]
    assert A.match_option("yes", opts) == "Yes"
    assert A.match_option("N/A – have never held U.S. security clearance", opts) == opts[2]
    assert A.match_option("None", opts) is None           # 'None' is not 'No'
    assert A.match_option("Yes, US citizen", ["Yes, I am eligible for a U.S. security clearance", "No"]) is None


# --- plan_fill ----------------------------------------------------------------

def test_exact_option_fills_and_mismatch_is_a_gap_with_options(identity, files):
    resume, _ = files
    fields = [
        _field("HISTORY WITH MERIDIAN", "value", "No", options=["Yes", "No"], name="question_a"),
        _field("CONFLICT OF INTEREST", "value", "None", options=["Yes", "No"], name="question_b"),
    ]
    plan = A.plan_fill(_packet(fields, resume), identity, resume_path=resume)
    sel = [a for a in plan["actions"] if a["type"] == "select"]
    assert sel == [{"type": "select", "name": "question_a", "option": "No", "label": "HISTORY WITH MERIDIAN",
                    "source": "answer file §E"}]
    assert len(plan["gaps"]) == 1
    g = plan["gaps"][0]
    assert g["kind"] == "option_mismatch"
    assert "CONFLICT OF INTEREST" in g["question"] and "Yes / No" in g["question"]
    assert "None" in g["question"]
    assert plan["ok"] is False


def test_inferred_answer_is_never_filled(identity, files):
    resume, _ = files
    fields = [_field("EXPORT CONTROLS - This position requires access to information subject to U.S. export controls.",
                     "value", "Yes, US citizen", inferred=True, source="answer file §F (inferred from 'Eligible'; logged)",
                     options=["A United States citizen or national", "None of the above"])]
    plan = A.plan_fill(_packet(fields, resume), identity, resume_path=resume)
    # nothing is filled FROM the inferred field — only attachments and the
    # identity-sourced standard location lookup may appear
    assert all(a["type"] in ("attach", "location") for a in plan["actions"])
    assert plan["gaps"][0]["kind"] == "inferred"
    assert "A United States citizen or national" in plan["gaps"][0]["question"]
    assert plan["ok"] is False


def test_attestation_label_needs_explicit_answer_file_source(identity, files):
    resume, _ = files
    fields = [_field("Are you legally authorized to work in the United States?", "value", "Yes",
                     source="WHY line generated with the letter", options=["Yes", "No"])]
    plan = A.plan_fill(_packet(fields, resume), identity, resume_path=resume)
    assert plan["gaps"][0]["kind"] == "attestation_unsourced"
    assert plan["ok"] is False


def test_acknowledgement_is_auto_acknowledged(identity, files):
    # operator policy 2026-08-31: routine consent/privacy acknowledgments are
    # ticked by the head, not left as gaps.
    resume, _ = files
    fields = [_field("We may use AI notetakers; please acknowledge our candidate privacy policy.", "value",
                     "Yes / acknowledged", source="§L rule 2 (inferred; logged)", inferred=True,
                     options=["I acknowledge"])]
    plan = A.plan_fill(_packet(fields, resume), identity, resume_path=resume)
    assert plan["ok"] and not plan["gaps"]
    assert any(a["option"] == "I acknowledge" for a in plan["actions"] if a["type"] == "select")


def test_identity_fields_map_from_identity_json(identity, files):
    resume, _ = files
    fields = [
        _field("First Name", "autofill", A.PROFILE, source="Jobright profile", name="first_name", ftype="input_text"),
        _field("Last Name", "autofill", A.PROFILE, source="Jobright profile", name="last_name", ftype="input_text"),
        _field("Email", "autofill", A.PROFILE, source="Jobright profile", name="email", ftype="input_text"),
        _field("Phone", "autofill", A.PROFILE, source="Jobright profile", name="phone", ftype="input_text", required=False),
        _field("LinkedIn Profile", "autofill", A.PROFILE, source="Jobright profile", name="question_l", ftype="input_text", required=False),
        _field("Website", "blank", "", source="§L rule 1 (optional, left blank)", name="question_w", ftype="input_text", required=False),
    ]
    plan = A.plan_fill(_packet(fields, resume), identity, resume_path=resume)
    by = {a["name"]: a for a in plan["actions"]}
    assert by["first_name"]["value"] == "Alex" and by["first_name"]["source"] == "identity.json:first_name"
    assert by["last_name"]["value"] == "Rivera"
    assert by["email"]["value"] == "applicant@example.org"
    assert by["phone"]["value"] == "555-010-0100"
    assert by["question_l"]["value"] == "https://linkedin.com/in/x"
    assert "question_w" not in by                     # blank stays blank
    assert plan["gaps"] == [] and plan["ok"] is True


def test_missing_identity_key_required_is_gap_optional_is_blank(identity, files):
    resume, _ = files
    ident = {k: v for k, v in identity.items() if k not in ("phone", "linkedin")}
    fields = [
        _field("Phone", "autofill", A.PROFILE, source="Jobright profile", name="phone", ftype="input_text", required=True),
        _field("LinkedIn Profile", "autofill", A.PROFILE, source="Jobright profile", name="question_l", ftype="input_text", required=False),
    ]
    plan = A.plan_fill(_packet(fields, resume), ident, resume_path=resume)
    assert [g["kind"] for g in plan["gaps"]] == ["identity"]
    assert all(a["name"] != "question_l" for a in plan["actions"])


def test_education_profile_field_is_a_gap_not_a_guess(identity, files):
    resume, _ = files
    fields = [_field("Which university did you last attend?", "autofill", A.PROFILE, source="Jobright profile",
                     name="question_u", ftype="input_text")]
    plan = A.plan_fill(_packet(fields, resume), identity, resume_path=resume)
    assert plan["gaps"][0]["kind"] in ("identity", "attestation_unsourced")
    assert plan["ok"] is False


def test_attachments_verified_by_sha256(identity, files):
    resume, letter = files
    fields = [
        _field("Resume/CV", "attach", resume.name, source="resume, unmodified", name="resume", ftype="input_file",
               extra={"inputs": [{"name": "resume", "type": "input_file", "values": []},
                                 {"name": "resume_text", "type": "textarea", "values": []}]}, required=False),
        _field("Cover Letter", "attach", letter.name, source="letters/ (Layer 5)", name="cover_letter", ftype="input_file",
               required=False, extra={"letter_field": True}),
    ]
    packet = _packet(fields, resume, letter)               # hashes taken at build time
    plan = A.plan_fill(packet, identity, resume_path=resume, letter_path=letter)
    att = {a["name"]: a for a in plan["actions"] if a["type"] == "attach"}
    assert att["resume"]["path"] == str(resume) and att["cover_letter"]["path"] == str(letter)
    assert plan["ok"] is True
    resume.write_bytes(b"%PDF changed")                   # resume drifted since the packet was built
    plan = A.plan_fill(packet, identity, resume_path=resume, letter_path=letter)
    assert plan["refusals"] and "resume" in plan["refusals"][0].lower()
    assert plan["ok"] is False


def test_text_answers_fill_text_inputs_and_essays(identity, files):
    resume, _ = files
    fields = [
        _field("Preferred name", "value", "Sam", source="answer file §H", name="question_p", ftype="input_text", required=False),
        _field("Discuss the risks of open source", "text", "Para one.\nPara two.", source="answer file §M (matched the form's own question)",
               name="question_e", ftype="textarea"),
    ]
    plan = A.plan_fill(_packet(fields, resume), identity, resume_path=resume)
    by = {a["name"]: a for a in plan["actions"]}
    assert by["question_p"] == {"type": "text", "name": "question_p", "value": "Sam", "label": "Preferred name", "source": "answer file §H"}
    assert by["question_e"]["value"] == "Para one.\nPara two."


def test_required_gap_field_from_packet_is_carried(identity, files):
    resume, _ = files
    fields = [_field("Tell us about a project", "GAP", "", source="free-text essay; answer file §L rule 3", name="question_t", ftype="textarea")]
    plan = A.plan_fill(_packet(fields, resume), identity, resume_path=resume)
    assert plan["gaps"][0]["kind"] == "uncovered" and plan["ok"] is False


def test_redacted_plan_hides_identity_values(identity, files):
    resume, _ = files
    fields = [_field("Email", "autofill", A.PROFILE, source="Jobright profile", name="email", ftype="input_text")]
    plan = A.plan_fill(_packet(fields, resume), identity, resume_path=resume)
    red = json.dumps(A.redact(plan))
    assert "applicant@example.org" not in red and "identity.json:email" in red


# --- identity.json ------------------------------------------------------------

def test_load_identity_checks_mode_and_email(tmp_path):
    p = tmp_path / "identity.json"
    p.write_text(json.dumps({"first_name": "N", "last_name": "P", "email": "applicant@example.org"}))
    os.chmod(p, 0o644)
    with pytest.raises(A.IdentityError, match="mode"):
        A.load_identity(p, env={"MAIL_ADDRESS": "applicant@example.org"})
    os.chmod(p, 0o600)
    assert A.load_identity(p, env={"MAIL_ADDRESS": "Applicant@Example.org"})["email"] == "applicant@example.org"
    with pytest.raises(A.IdentityError, match="MAIL_ADDRESS"):
        A.load_identity(p, env={"MAIL_ADDRESS": "other@example.org"})
    with pytest.raises(A.IdentityError, match="missing"):
        A.load_identity(tmp_path / "nope.json", env={"MAIL_ADDRESS": "x"})


# --- review finding #3: the phone action carries the country for the form's selector ----

def test_phone_action_carries_identity_country(identity, files):
    resume, _ = files
    fields = [_field("Phone", "autofill", A.PROFILE, source="Jobright profile", name="phone", ftype="input_text", required=False)]
    plan = A.plan_fill(_packet(fields, resume), identity, resume_path=resume)
    a = plan["actions"][0]
    assert a["name"] == "phone" and a["country"] == "United States"
    ident = {k: v for k, v in identity.items() if k != "country"}
    plan = A.plan_fill(_packet(fields, resume), ident, resume_path=resume)
    assert "country" not in plan["actions"][0]
    assert "United States" not in json.dumps(A.redact(plan))           # redaction covers it


# --- voluntary self-ID actions are optional: attempted, never a door ----------

def test_demographic_select_actions_are_marked_optional(files):
    resume, _ = files
    fields = [_field("Gender", "value", "Decline To Self Identify", required=False,
                     source="answer file, Identity/EEO block: decline to self-identify",
                     name="gender", options=["Decline To Self Identify", "Female", "Male"],
                     extra={"demographic": True})]
    plan = A.plan_fill(_packet(fields, resume), {"first_name": "N", "last_name": "P", "email": "e@x.org"},
                       resume_path=resume, letter_path=None)
    acts = [a for a in plan["actions"] if a["type"] == "select"]
    assert len(acts) == 1 and acts[0]["option"] == "Decline To Self Identify"
    assert acts[0].get("optional") is True
    assert plan["ok"]


# --- auto-acknowledge routine consents (operator policy 2026-08-31) -----------
# The head may tick privacy/consent/agree fields on its own. It must NOT auto-
# sign the weighty legal attestations (background-check authorization, I-9,
# "certify true under penalty") — those still route to manual.

def test_auto_acknowledges_a_privacy_consent_checkbox(files):
    resume, _ = files
    fields = [_field("Please review and acknowledge Cloudmere's Candidate Privacy Policy",
                     "value", "Acknowledge/Confirm & Yes / acknowledged", required=True,
                     source="answer file §E", name="q_priv",
                     ftype="multi_value_multi_select", options=["Acknowledge/Confirm"])]
    plan = A.plan_fill(_packet(fields, resume), {"first_name": "N", "last_name": "P", "email": "e@x.org"},
                       resume_path=resume, letter_path=None)
    assert plan["ok"] and not plan["gaps"]
    chk = [a for a in plan["actions"] if a["type"] == "check"]   # a checkbox, ticked
    assert len(chk) == 1 and chk[0]["option"] == "Acknowledge/Confirm"


def test_agree_to_terms_single_option_is_ticked(files):
    resume, _ = files
    fields = [_field("I agree to the terms and conditions", "GAP", "", required=True,
                     source="§L", name="q_terms", ftype="multi_value_single_select",
                     options=["I agree"], inferred=True)]
    plan = A.plan_fill(_packet(fields, resume), {"first_name": "N", "last_name": "P", "email": "e@x.org"},
                       resume_path=resume, letter_path=None)
    assert plan["ok"] and any(a["option"] == "I agree" for a in plan["actions"] if a["type"] == "select")


def test_background_check_authorization_is_NOT_auto_signed(files):
    resume, _ = files
    fields = [_field("I authorize a background check and certify the above is true under penalty of perjury",
                     "value", "acknowledged", required=True, source="§L", name="q_bg",
                     ftype="multi_value_single_select", options=["I authorize", "I do not authorize"], inferred=True)]
    plan = A.plan_fill(_packet(fields, resume), {"first_name": "N", "last_name": "P", "email": "e@x.org"},
                       resume_path=resume, letter_path=None)
    assert not plan["ok"]                                    # stays a gap -> routes to manual
    assert any("authorize a background check" in g["label"] for g in plan["gaps"])
