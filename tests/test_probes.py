"""Form probes for Lever (JSON card schema in the apply page) and Ashby
(public GraphQL). No network: canned page / canned response."""
import json

import submission as S
from sources import common

LEVER_PAGE = """<html><body>
<form id="application-form" enctype="multipart/form-data" method="POST">
<div class="application-label">Resume/CV ✱</div>
<input data-qa="input-resume" id="resume-upload-input" name="resume" type="file">
<div class="application-label">Full name ✱</div><input type="text" name="name" required>
<div class="application-label">Email ✱</div><input name="email" type="email" required>
<div class="application-label">Phone</div><input type="text" name="phone">
<div class="application-label">Current location ✱</div><input id="location-input" type="text" name="location" required>
<div class="application-label">LinkedIn URL</div><input type="text" name="urls[LinkedIn]">
<input type="hidden" value="{&quot;text&quot;:&quot;Work Authorization&quot;,&quot;fields&quot;:[{&quot;type&quot;:&quot;multiple-choice&quot;,&quot;text&quot;:&quot;Are you legally authorized to work in the country for which you are applying?&quot;,&quot;required&quot;:true,&quot;id&quot;:&quot;x1&quot;,&quot;options&quot;:[{&quot;text&quot;:&quot;Yes&quot;},{&quot;text&quot;:&quot;No&quot;}]},{&quot;type&quot;:&quot;text&quot;,&quot;text&quot;:&quot;Preferred Name | What would you like us to call you?&quot;,&quot;required&quot;:false,&quot;id&quot;:&quot;x2&quot;,&quot;options&quot;:[]}]}" name="cards[aaaa][baseTemplate]">
<input type="hidden" value="{&quot;text&quot;:&quot;Languages&quot;,&quot;fields&quot;:[{&quot;type&quot;:&quot;multiple-select&quot;,&quot;text&quot;:&quot;Language Skill(s) (Check all that apply)&quot;,&quot;required&quot;:true,&quot;id&quot;:&quot;x3&quot;,&quot;options&quot;:[{&quot;text&quot;:&quot;English (ENG)&quot;},{&quot;text&quot;:&quot;Spanish (SPA)&quot;}]},{&quot;type&quot;:&quot;dropdown&quot;,&quot;text&quot;:&quot;How did you hear about us?&quot;,&quot;required&quot;:true,&quot;id&quot;:&quot;x4&quot;,&quot;options&quot;:[{&quot;text&quot;:&quot;LinkedIn&quot;},{&quot;text&quot;:&quot;Indeed&quot;}]}]}" name="cards[bbbb][baseTemplate]">
<textarea name="comments" id="additional-information"></textarea>
<div id="h-captcha" class="h-captcha" data-sitekey="k"></div><input name="h-captcha-response">
<button id="btn-submit" type="button">Submit application</button>
</form></body></html>"""


def test_probe_lever_reads_cards_and_top_fields(monkeypatch):
    monkeypatch.setattr(common, "http", lambda url, **k: (200, LEVER_PAGE.encode(), url))
    f = S.probe_lever("https://jobs.lever.co/acme/12345678-1234-1234-1234-123456789abc")
    assert f["platform"] == "lever" and f["status"] == "read" and f["captcha"] is True
    assert f["apply_url"].endswith("/apply")
    by = {x["label"]: x for x in f["fields"]}
    assert by["Full name"]["required"] and by["Full name"]["inputs"] == [{"name": "name", "type": "input_text", "values": []}]
    assert by["Resume/CV"]["required"] and by["Resume/CV"]["inputs"][0] == {"name": "resume", "type": "input_file", "values": []}
    assert not by["Phone"]["required"] and by["Current location"]["required"]
    assert by["LinkedIn URL"]["inputs"][0]["name"] == "urls[LinkedIn]"
    assert "GitHub URL" not in by                                    # only inputs the page actually has
    q = by["Are you legally authorized to work in the country for which you are applying?"]
    assert q["required"] and q["inputs"] == [{"name": "cards[aaaa][field0]", "type": "radio", "values": ["Yes", "No"]}]
    assert q["options"] == ["Yes", "No"]
    assert by["Preferred Name | What would you like us to call you?"]["inputs"][0] == {"name": "cards[aaaa][field1]", "type": "input_text", "values": []}
    assert by["Language Skill(s) (Check all that apply)"]["inputs"][0]["type"] == "checkbox"
    assert by["How did you hear about us?"]["inputs"][0] == {"name": "cards[bbbb][field1]", "type": "select", "values": ["LinkedIn", "Indeed"]}
    assert by["Additional information"]["inputs"][0]["name"] == "comments"


def test_probe_lever_without_captcha(monkeypatch):
    page = LEVER_PAGE.replace('<div id="h-captcha" class="h-captcha" data-sitekey="k"></div><input name="h-captcha-response">', "")
    monkeypatch.setattr(common, "http", lambda url, **k: (200, page.encode(), url))
    f = S.probe_lever("https://jobs.lever.co/acme/12345678-1234-1234-1234-123456789abc")
    assert f["captcha"] is False


ASHBY_RESP = {"data": {"jobPosting": {"id": "j1", "title": "Security Engineer", "applicationForm": {"sections": [{"title": None, "fieldEntries": [
    {"isRequired": True, "isHidden": False, "field": {"path": "_systemfield_name", "title": "First and Last Name", "type": "String", "isNullable": False}},
    {"isRequired": True, "isHidden": False, "field": {"path": "_systemfield_location", "title": "Location", "type": "Location"}},
    {"isRequired": True, "isHidden": False, "field": {"path": "_systemfield_email", "title": "Email", "type": "Email"}},
    {"isRequired": True, "isHidden": False, "field": {"path": "_systemfield_resume", "title": "Resume", "type": "File"}},
    {"isRequired": False, "isHidden": False, "field": {"path": "cover_letter", "title": "Cover Letter (optional)", "type": "File"}},
    {"isRequired": True, "isHidden": False, "field": {"path": "question_1", "title": "Do you currently have authorization to work in the US?", "type": "Boolean"}},
    {"isRequired": True, "isHidden": False, "field": {"path": "q_essay", "title": "Why do you want to join Quartzline?", "type": "LongText"}},
    {"isRequired": False, "isHidden": False, "field": {"path": "question_2", "title": "How did you hear about this job?", "type": "ValueSelect",
                                                        "selectableValues": [{"label": "LinkedIn", "value": "li"}, {"label": "Friend (Referral)", "value": "fr"}]}},
    {"isRequired": False, "isHidden": True, "field": {"path": "secret", "title": "hidden thing", "type": "String"}},
]}]}}}}


def test_probe_ashby_reads_graphql_schema(monkeypatch):
    seen = {}
    def fake_http(url, **k):
        seen["url"] = url; seen["body"] = k.get("body"); seen["headers"] = k.get("headers")
        return 200, json.dumps(ASHBY_RESP).encode(), url
    monkeypatch.setattr(common, "http", fake_http)
    f = S.probe_ashby("https://jobs.ashbyhq.com/quartzline/ac1cb3c4-5408-4912-8591-eea2a84480b7")
    assert seen["url"].startswith("https://jobs.ashbyhq.com/api/non-user-graphql")
    assert seen["body"]["variables"] == {"organizationHostedJobsPageName": "quartzline", "jobPostingId": "ac1cb3c4-5408-4912-8591-eea2a84480b7"}
    assert f["platform"] == "ashby" and f["status"] == "read" and f["captcha"] is False
    assert f["apply_url"] == "https://jobs.ashbyhq.com/quartzline/ac1cb3c4-5408-4912-8591-eea2a84480b7/application"
    by = {x["label"]: x for x in f["fields"]}
    assert "hidden thing" not in by
    assert by["First and Last Name"]["inputs"] == [{"name": "_systemfield_name", "type": "input_text", "values": []}]
    assert by["Location"]["inputs"][0]["type"] == "location"
    assert by["Resume"]["required"] and by["Resume"]["inputs"][0]["type"] == "input_file"
    assert by["Do you currently have authorization to work in the US?"]["inputs"] == [{"name": "question_1", "type": "boolean", "values": ["Yes", "No"]}]
    assert by["Do you currently have authorization to work in the US?"]["options"] == ["Yes", "No"]
    assert by["Why do you want to join Quartzline?"]["inputs"][0]["type"] == "textarea"
    assert by["How did you hear about this job?"]["inputs"][0] == {"name": "question_2", "type": "select", "values": ["LinkedIn", "Friend (Referral)"]}


def test_probe_ashby_http_failure(monkeypatch):
    monkeypatch.setattr(common, "http", lambda url, **k: (403, b"", url))
    f = S.probe_ashby("https://jobs.ashbyhq.com/quartzline/ac1cb3c4-5408-4912-8591-eea2a84480b7")
    assert f["status"] == "http 403" and f["fields"] is None


def test_probe_form_routes_ashby_and_lever():
    assert S.platform_of("https://jobs.ashbyhq.com/quartzline/x") == "ashby"
    assert S.platform_of("https://jobs.lever.co/graphite/x") == "lever"


def test_work_authorization_wording_maps(monkeypatch):
    import answers
    bank = {"ID": {"Work authorization": "authorized to work in the US, no sponsorship required"}, "_titles": {}, "_notes": {}}
    monkeypatch.setattr(answers, "find_by_label", lambda bank, label: (None, None))
    row = {"cover_letter_path": None, "company": "Quartzline", "source": "company_page"}
    d = S.map_field({"label": "Do you currently have authorization to work in the US?", "required": True}, row, bank, {})
    assert d["fill"] == "value" and d["value"] == "Yes"


def test_commute_question_maps_to_commute_not_on_call(monkeypatch):
    import answers
    bank = {"B": {"Weekends or on-call rotation": "Yes"}, "C": {"Max one-way commute": "45 miles / 60 minutes"}, "_titles": {}, "_notes": {}}
    monkeypatch.setattr(answers, "find_by_label", lambda bank, label: (None, None))
    row = {"cover_letter_path": None, "company": "Graphite Analytics", "source": "company_page"}
    d = S.map_field({"label": "Are you willing and able to commute to our Georgetown office within one hour when on-call?", "required": True}, row, bank, {})
    assert d["value"] == "45 miles / 60 minutes" and "§C" in d["source"]


# --- Greenhouse compliance (EEO self-ID) questions become packet fields -------

GH_API = json.dumps({
    "absolute_url": "https://job-boards.greenhouse.io/x/jobs/1",
    "questions": [{"label": "Email", "required": True,
                   "fields": [{"name": "email", "type": "input_text", "values": []}]}],
    "compliance": [{"type": "eeoc", "questions": [
        {"label": "Gender", "required": False,
         "fields": [{"name": "gender", "type": "multi_value_single_select",
                     "values": [{"label": "Decline To Self Identify"}, {"label": "Female"}, {"label": "Male"}]}]}]}],
})


def test_probe_greenhouse_includes_compliance_questions(monkeypatch):
    monkeypatch.setattr(common, "http", lambda url, **k: (200, GH_API.encode(), url))
    form = S.probe_greenhouse("https://boards.greenhouse.io/x/jobs/1")
    by = {f["label"]: f for f in form["fields"]}
    assert "Gender" in by and by["Gender"]["demographic"] is True
    assert "Decline To Self Identify" in by["Gender"]["options"]
    assert not by["Email"].get("demographic")


def test_sponsorship_and_authorization_defaults_are_us_scoped_only(monkeypatch):
    """§ID's authorization line answers US employment. A question scoped to
    any other country must come from the bank explicitly or become a gap —
    never a defaulted attestation (live miss: a foreign-scoped sponsorship question
    auto-answered 'No' from the US default, 2026-09-01)."""
    import answers
    bank = {"ID": {"Work authorization": "authorized to work in the US, no sponsorship required"}, "_titles": {}, "_notes": {}}
    monkeypatch.setattr(answers, "find_by_label", lambda bank, label: (None, None))
    row = {"cover_letter_path": None, "company": "Cloudmere", "source": "company_page"}
    m = lambda label: S.map_field({"label": label, "required": True}, row, bank, {})
    # generic and US-explicit forms keep the truthful defaults
    d = m("Will you now or in the future require sponsorship for employment visa status?")
    assert d["fill"] == "value" and d["value"] == "No"
    d = m("Do you require sponsorship to work in the United States?")
    assert d["fill"] == "value" and d["value"] == "No"
    d = m("Are you legally authorized to work in the U.S.?")
    assert d["fill"] == "value" and d["value"] == "Yes"
    # foreign-scoped forms gap instead of guessing
    d = m("Do you now or will you in the future require immigration sponsorship to work at Cloudmere in Japan?")
    assert d["fill"] == "GAP" and "japan" in d["source"].lower()
    d = m("Are you legally authorized to work in Singapore?")
    assert d["fill"] == "GAP" and "singapore" in d["source"].lower()
