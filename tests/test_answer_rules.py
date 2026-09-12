"""Operator attestations added 2026-08-29 in the Greenhouse form's exact option
wording, and the general 'how did you hear' rule. Uses the REAL answer file
(read-only) so a paraphrase would fail here."""
import answers
import submission as S

ROW_CO = {"cover_letter_path": None, "company": "Meridian Dynamics", "source": "company_page"}
ROW_LI = {"cover_letter_path": None, "company": "Meridian Dynamics", "source": "linkedin"}


def _field(label, options, required=True):
    return {"label": label, "required": required, "kind": "multi_value_single_select",
            "inputs": [{"name": "q", "type": "multi_value_single_select", "values": options}]}


def test_clearance_eligibility_is_the_exact_option():
    bank = answers.load()
    d = S.map_field(_field("CLEARANCE ELIGIBILITY - This position requires eligibility to obtain and maintain a U.S. security clearance.",
                           ["Yes, I hold an active U.S. security clearance", "Yes, I am eligible for a U.S. security clearance", "No"]), ROW_CO, bank, {})
    assert d["value"] == "Yes, I am eligible for a U.S. security clearance" and "§F" in d["source"] and not d.get("inferred")


def test_past_clearance_level_is_the_exact_option():
    bank = answers.load()
    d = S.map_field(_field("If you have held a U.S. security clearance in the past, what clearance level have you held? ",
                           ["N/A - have never held U.S. security clearance", "Confidential", "Secret", "Top Secret"]), ROW_CO, bank, {})
    assert d["value"] == "N/A - have never held U.S. security clearance" and "§F" in d["source"] and not d.get("inferred")


def test_current_clearance_still_none_for_the_hold_question():
    bank = answers.load()
    d = S.map_field(_field("Do you currently hold an active US security clearance?", ["Yes", "No"]), ROW_CO, bank, {})
    assert d["value"] == "None" and "§F" in d["source"]


def test_export_controls_is_sourced_not_inferred():
    bank = answers.load()
    d = S.map_field(_field("EXPORT CONTROLS - This position requires access to information and technology that is subject to U.S. export controls. Your responses to the questions below will be used solely to determine your eligibility under U.S. law to receive information and materials subject to U.S. export controls.",
                           ["A United States citizen or national", "A person lawfully admitted for permanent residence of the United States (i.e., “Green Card” holder)", "None of the above"]), ROW_CO, bank, {})
    assert d["value"] == "A United States citizen or national"
    assert d["source"].startswith("answer file §F") and not d.get("inferred")


def test_conflict_of_interest_is_no():
    bank = answers.load()
    d = S.map_field(_field("CONFLICT OF INTEREST", ["Yes", "No"]), ROW_CO, bank, {})
    assert d["value"] == "No" and "§E" in d["source"]


def test_how_did_you_hear_prefers_the_company_site_option_when_found_there():
    bank = answers.load()
    opts = ["Google job search", "Indeed", "LinkedIn", "Meridian Website", "ClearanceJobs"]
    d = S.map_field(_field("How did you hear about Meridian?", opts), ROW_CO, bank, {})
    assert d["value"] == "Meridian Website" and "§H" in d["source"]
    # a board-sourced row picks the board's option
    d = S.map_field(_field("How did you hear about Meridian?", opts), ROW_LI, bank, {})
    assert d["value"] == "LinkedIn"
    # careers-page wording counts as the company's site
    d = S.map_field(_field("How did you hear about this job?", ["Quartzline jobs site", "Friend (Referral)", "Twitter"]),
                    {"cover_letter_path": None, "company": "Quartzline", "source": "company_page"}, bank, {})
    assert d["value"] == "Quartzline jobs site"
    # no such option: the generic answer stays (and becomes an option gap in the head)
    d = S.map_field(_field("How did you hear about Meridian?", ["Google job search", "Indeed"]), ROW_CO, bank, {})
    assert d["value"] == "Company website"
    # a text field (no options) keeps the generic answer
    d = S.map_field({"label": "How did you hear about us?", "required": True, "kind": "input_text",
                     "inputs": [{"name": "q", "type": "input_text", "values": []}]}, ROW_CO, bank, {})
    assert d["value"] == "Company website"


# --- identity source labels + voluntary self-identification (operator, 2026-08-31) ---

def test_identity_block_self_id_rows_load():
    bank = answers.load()
    for field in ("Gender self-identification",
                  'Race / ethnicity self-identification (incl. "Are you Hispanic/Latino?")',
                  "Veteran status self-identification",
                  "Disability status self-identification"):
        assert bank["ID"][field] == "Decline to self-identify", field


def test_profile_source_names_identity_json_and_handoff():
    bank = answers.load()
    d = S.map_field({"label": "First Name", "required": True, "kind": "input_text",
                     "inputs": [{"name": "first_name", "type": "input_text", "values": []}]}, ROW_CO, bank, {})
    assert d["fill"] == "autofill"
    assert "identity.json" in d["source"] and "Jobright" in d["source"]


def test_self_id_dropdowns_decline_in_the_forms_own_wording():
    bank = answers.load()
    cases = [
        ("Gender", ["Decline To Self Identify", "Female", "Male"], "Decline To Self Identify"),
        ("Are you Hispanic/Latino?", ["Yes", "No", "Decline To Self Identify"], "Decline To Self Identify"),
        ("Race", ["Decline To Self Identify", "White", "Asian"], "Decline To Self Identify"),
        ("VeteranStatus", ["I don't wish to answer", "I am not a protected veteran"], "I don't wish to answer"),
        ("Veteran Status", ["I don't wish to answer", "I am not a protected veteran"], "I don't wish to answer"),
        ("DisabilityStatus", ["I do not want to answer", "No, I do not have a disability and have not had one in the past"], "I do not want to answer"),
    ]
    for label, opts, want in cases:
        d = S.map_field(_field(label, opts, required=False), ROW_CO, bank, {})
        assert d.get("value") == want, label
        assert d.get("demographic") is True and not d.get("inferred")
        assert "decline" in (d.get("source") or "").lower()


def test_self_id_without_a_decline_option_stays_blank_not_a_gap():
    bank = answers.load()
    d = S.map_field(_field("Gender", ["Female", "Male"], required=False), ROW_CO, bank, {})
    assert d["fill"] == "blank" and d.get("demographic") is True


def test_accommodation_questions_are_not_self_id():
    bank = answers.load()
    d = S.map_field(_field("Do you require a disability accommodation to perform this job?",
                           ["Yes", "No"]), ROW_CO, bank, {})
    assert not d.get("demographic")
    assert d.get("value") not in ("I do not want to answer", "Decline To Self Identify")
