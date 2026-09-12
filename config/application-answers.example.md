# Application Answers (runtime config — EXAMPLE)

Copy this file to `config/application-answers.md` and replace every value with
your own truthful answer. The automation reads that file before every
application. Every ATS field gets answered from it. Nothing is invented. If a
form asks something not covered below, the rule is in section L.

Many of these are attestations on signed forms (salary, experience durations,
clearance, criminal history, work authorization, education). Write only what is
true for you.

---

## Identity, EEO, and work history

Contact identity (name, email, phone, links) lives in `identity.json` (mode
600, git-ignored), the only identity source the autonomous head reads.
Education, employment history, and skills stay in the resume.

Work authorization: authorized to work in the US, no sponsorship required now or in future.

Voluntary self-identification: decline every EEO self-ID question, in the form's own decline wording. (Answer them if you prefer; edit the cells.)

| Field | Answer |
| :---- | :---- |
| Gender self-identification | Decline to self-identify |
| Race / ethnicity self-identification (incl. "Are you Hispanic/Latino?") | Decline to self-identify |
| Veteran status self-identification | Decline to self-identify |
| Disability status self-identification | Decline to self-identify |

---

## A. Compensation

| Field | Answer |
| :---- | :---- |
| Minimum base salary | $50,000 |
| Target base salary | $85,000 |
| "Desired salary" when a single number is required | $90,000 |
| Hourly equivalent | $40/hr |
| Minimum hourly if the role is fully remote | $25/hr |
| Salary negotiable | Yes |

---

## B. Timing and availability

| Field | Answer |
| :---- | :---- |
| Earliest start date | Two weeks from written offer |
| Currently employed | Yes, BitBench |
| May we contact current employer | Yes |
| Night shift or rotating shift | **Yes** |
| Weekends or on-call rotation | **Yes** |
| Maximum travel | 100% |
| Do you have any, or anticipate any upcoming offer deadlines? | Not at the moment, no. |

Night and weekend availability is a differentiator on 24/7 SOC floors. Where a posting mentions shift coverage, the cover letter should say so explicitly.

---

## C. Location

| Field | Answer |
| :---- | :---- |
| Current location | 123 Example St, Rivertown, NY 10000 |
| Max one-way commute | 45 miles / 60 minutes |
| Remote vs hybrid vs onsite | No preference, all acceptable |
| Willing to relocate | Yes, anywhere |
| Relocation assistance | Preferred, not required |
| Do you currently live or are you willing to relocate to the job's location? | I am willing to relocate to this job's location. |

**Relocation note:** answering "required" on a relocation-assistance field screens you out at smaller employers and most entry-level reqs, since few budget for it at this level. Unless you genuinely can't move without it, keep the cell above at **Preferred, not required**. Change the cell if you disagree and the system will use whatever it says.

---

## D. Experience figures

Used identically on every application so nothing contradicts across submissions.

| Field | Answer |
| :---- | :---- |
| Years of professional IT experience | **3** |
| Years of professional cybersecurity experience | **3** |
| Years with Splunk | 1 |
| Years with SIEM tools generally | 2 |
| Years with Linux | 5 |
| Years with network security / firewalls | 3 |
| Years with Python or scripting | 2 |

Set these once, truthfully; every application uses them identically. Edit the cells to change them.

---

## E. Standard fields

| Field | Answer |
| :---- | :---- |
| Valid driver's license | Yes |
| Reliable transportation | Yes |
| Background check | Yes |
| Drug screen | Yes |
| Convicted of a felony | No |
| Previously employed here | No |
| Related to a current employee | No |
| Subject to a non-compete | No |
| 18 or older | Yes |
| Certifications held | None |
| Certifications in progress | CompTIA Security+, CompTIA Network+ |
| Language skills | English, native |
| Conflict of interest | No |
| Legal Name (if different than above) | Alex Rivera |
| First and Last Name | Alex Rivera |
| Phone number | 5550100100 |

"Previously employed here" has one code-level exception: a posting from your
current employer answers "Yes" (see `answers.previously_employed`; set
`CURRENT_EMPLOYER_RX` there to your employer).

---

## F. Clearance

| Field | Answer |
| :---- | :---- |
| Current clearance | None |
| Eligible | Yes, I am eligible for a U.S. security clearance |
| Clearance level held in the past | N/A - have never held U.S. security clearance |
| Export controls / U.S. person status | A United States citizen or national |
| Willing to undergo investigation | Yes |

Attest these in the exact option wording of the first form you meet them on.
Every application uses these cells as written; a form whose options differ
becomes an answer gap, never a guess.

---

## G. References

1. **First Last** — Relationship, Employer [ref1@example.org](mailto:ref1@example.org) · 555-010-0101
2. **First Last** — Relationship, Employer [ref2@example.org](mailto:ref2@example.org) · 555-010-0102
3. **First Last** — Relationship, Employer [ref3@example.org](mailto:ref3@example.org) · 555-010-0103

Confirm all three know they're listed before the first batch goes out. Reference calls from an unexpected employer land badly.

---

## H. Free-text defaults

| Field | Answer |
| :---- | :---- |
| How did you hear about this position | Company website |
| Preferred name | Alex |
| Pronouns | They/Them |
| Feel free to share something interesting that we might not get from your resume! [Your github, your portfolio, a link to your startup or nonprofit, etc.] | GitHub: https://github.com/example Website/Portfolio: example.org |

Two fields are answered by code, not by a cell here: when the posting came from a job board, "How did you hear" becomes that board's name (`materials.BOARD_NAME`); "Why are you interested" is always the WHY line generated with the cover letter (`submission.map_field`), and with no letter it is an answer gap, never a template.

"How did you hear" on a dropdown: when discovery found the job on the company's own site and the form offers a "[Company] Website" / "[Company] jobs site" / "careers page" style option, select that option; when it came from a board, select the board's option (Indeed, LinkedIn, Glassdoor, ZipRecruiter). If the list has no such option the generic cell above stays, which on a dropdown is an answer gap, never a guess.

---

## I. Filters

**All filters off.** Apply to everything that matches a target role title.

- No experience-level ceiling
- No salary floor rejection
- No keyword rejection
- Staffing agencies included

---

## J. Targeting

No fixed company list. Apply broadly across anything matching the role titles below (kept in sync with `titles_tier_*` in config.json).

**Tier A:** SOC Analyst, SOC Analyst I/Tier 1, Security Analyst, Cybersecurity Analyst, Information Security Analyst, Security Operations Analyst, Threat Detection Analyst

**Tier B:** Network Engineer, Network Security Engineer, NOC Technician, IT Security Specialist, Junior Penetration Tester, GRC Analyst, Incident Response Analyst

**Tier C:** Systems Administrator, IT Analyst, Desktop Support Tier 2, Help Desk Tier 2, Technical Support Engineer, IT Generalist

**Company list builds itself.** Rather than a static list, the system records every employer whose posting scores above 70, adds them to a running target file (`targets.json`), and scrapes their careers page directly from then on. Roles sit on company career pages before they reach the boards, so the list gets more valuable each week without you maintaining it.

---

## K. Jobright

| Field | Answer |
| :---- | :---- |
| Plan | Turbo |
| Agent (auto-apply) | **Active** |

Only relevant if you route manual handoffs through Jobright's autofill; delete the section otherwise.

---

## L. Unanswered-question rule

When a form asks something this file doesn't cover:

1. Optional field → leave blank, apply, log the question to the nightly review
2. Required field, and a reasonable answer is inferable from this file → use it, apply, log the inference to the nightly review
3. Required field, nothing inferable → skip the job, log why

Questions logged this way get added to this file so the same gap never blocks twice.

**Never** invent an answer for: salary, experience duration, clearance, criminal history, work authorization, or education. Those are attestations. If one is unanswerable from this file, skip the job.

---

## M. Answers added from chat

Rows appended by the chat agent after operator confirmation. Each one closes an answer gap; edit freely. A `<br>` inside an answer is a paragraph break (essay fields keep their paragraphs).

| Field | Answer |
| :---- | :---- |
| Willing to take a polygraph (posting mentions) | Yes |
