# Security and responsible use

jobbot ingests text written by strangers all day and holds real credentials.
Treat it as a prompt-injection surface, because it is one.

## Threat model

- **Untrusted input.** Every job posting is attacker-controlled text. A posting
  can contain instructions aimed at the model. Posting text is delimited in
  every prompt and labeled as data; the model is told nothing inside the
  delimiters is an instruction. Scoring flags postings that address automated
  systems and quarantines them instead of acting on them.
- **Privileged surface.** The chat daemon is the only component with tool
  access. Only rows written by the dashboard chat reach it. Scraped content
  never enters that context. `draft_email` returns a draft and never sends.
- **Credentials.** `.env` is mode 600 and gitignored. The mailbox password and
  API key live nowhere else. Set a hard monthly spend cap on the API key.
- **Blast radius.** Run it in an unprivileged container on its own VLAN with a
  firewall between the container and everything you care about. Nothing
  inbound from the WAN; remote access over a tailnet only.
- **Your resume.** Mode 444. It ships byte-for-byte on every application.

## Lines the bot does not cross

- Autonomous submission is limited to applicant tracking systems on the
  employer's own domain (Greenhouse, Lever, Ashby, Workable).
- LinkedIn, Indeed, Glassdoor, and Jobright native forms are never scripted.
  Those platforms forbid it. They route to the Manual Queue for a human.
- CAPTCHAs and human-verification walls are never attempted. The domain is
  remembered and pre-routed to a human from then on.
- Export-control and clearance questions are answered only from exact-option
  matches in the answer bank, never inferred.
- One handoff per company per title per day.

## Defaults

- `DRY_RUN=true`. The submit head logs what it would do and does not click.
- The first twenty live sends each capture a confirmation screenshot for review.
- Every job checks for a `PAUSE` file before doing anything. `touch PAUSE`
  stops the whole system.

## Before you go live

1. Rotate the mailbox password to something unique and generated.
2. Audit which accounts use that mailbox for password reset.
3. Set the API spend cap.
4. Run discovery, scoring, and letters live with submission in dry-run for at
   least two days. Read the nightly reports.
5. Flip `DRY_RUN` deliberately, watch the first twenty screenshots, then decide.

## Reporting a problem

Open an issue. Do not include credentials, answer-bank contents, or employer
correspondence in the report.
