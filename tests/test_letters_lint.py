"""letters.py lint — the start-date / graduation-tense check. The operator
graduated May 2026: still-enrolled or start-date phrasing must fail, but the
correct past constructions "since graduating" / "after finishing my degree"
must pass (they blocked letter #347 three times on 2026-08-31).
The message must quote the matched phrase so a retry can actually fix it."""
import letters as L


def _tense_items(text):
    return [x for x in L.lint_short(text) if x.startswith("start date / graduation tense")]


def test_past_graduation_constructions_are_clean():
    assert _tense_items("Since graduating in May, I have worked at BitBench.") == []
    assert _tense_items("After finishing my degree in May 2026, I kept building the lab.") == []


def test_student_or_start_phrasing_still_trips():
    for bad in ("I am graduating this spring.",
                "I will graduate in May 2027.",
                "I can start immediately.",
                "My expected graduation is May 2027.",
                "I am finishing my degree now."):
        assert _tense_items(bad), bad


def test_tense_message_quotes_the_matched_phrase():
    items = _tense_items("I am graduating this spring.")
    assert items and "'graduating'" in items[0]


# --- commute claims: letters must not assert distance feasibility ------------
# (§C: example applicant, 45 mi / 60 min max — but relocate-anywhere is true for
# every posting, so that is the only location claim a letter may make. Caught
# live 2026-08-31: 'the commute is manageable' about Adelphi, MD, ~250 miles.)

def _hard(body):
    hard, _ = L.lint(body + "\n\nSecond paragraph for structure.\n\nAcme is the company named here.",
                     company="Acme")
    return hard


def test_commute_feasibility_claims_hard_fail():
    for bad in ("Acme is in Adelphi and the commute is manageable from Rivertown.",
                "Adelphi is a reasonable commute from Rivertown.",
                "Your office is an easy drive from my home."):
        assert any("commute" in h for h in _hard(bad)), bad


def test_relocation_openness_is_fine():
    assert not any("commute" in h for h in _hard("I am open to relocating for this role."))
