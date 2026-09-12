# Reproduce jobbot end to end

This is the shortest honest path from nothing to a running, safe copy of jobbot. It links out to the two longer documents instead of repeating them.

## 0. Decide whether you should run this at all

jobbot submits applications in your name, holds your mailbox password and an API key, and reads text written by strangers all day. Read [SECURITY.md](../SECURITY.md) first. If you are not comfortable running an unprivileged container on its own VLAN with a spend cap on the API key, stop here and use the Manual Queue idea by hand instead.

## 1. Build the box (about 3 hours)

Follow [BUILD-GUIDE.md](BUILD-GUIDE.md) top to bottom. It ends with a connection test for every external dependency: internet, IMAP, SMTP, ntfy, the API, and the dashboard from your phone over cell data. Do not continue until all of them pass.

What you have at the end: an unprivileged Ubuntu 24.04 LXC on a Lab VLAN with Tailscale, Caddy on :80, ntfy on :2586, a locked `.env`, a filled answer bank, and a read-only resume.

## 2. Install the pipeline (10 minutes)

```
cd ~/jobbot
python3 -m venv venv
./venv/bin/pip install -r requirements.txt
./venv/bin/playwright install chromium
cp identity.example.json identity.json && chmod 600 identity.json   # then fill it in
cp targets.example.json targets.json                                # then list your companies
cp config/application-answers.example.md config/application-answers.md   # then fill it in
./venv/bin/python -c "import db; db.init_db(); print('schema ok at', db.DB_PATH)"
```

Point Caddy at the dashboard and install the two services. `install-services.sh` copies the shipped `deploy/Caddyfile` into place, fills the systemd unit placeholders with your user and checkout path, and health-checks the result:

```
sudo bash install-services.sh
```

Open `http://jobbot` (Tailscale) or the container IP (Trusted VLAN). You should see the Overview page with empty panels.

## 3. Dry run (two days)

The shipped `config.json` is already in dry run (`submission.dry_run: true`, `inbox_pass.dry_run: true`, browser head disabled). Run each stage by hand once so you can read what it does:

```
./venv/bin/python discovery.py      # pulls postings, dedupes, tags apply_route, then runs scoring and letters
./venv/bin/python submission.py     # dry run: logs what it would do, clicks nothing
./venv/bin/python inbox.py          # dry run: classifies your inbox without writing to the tracker
./venv/bin/python report.py         # emails you the nightly report
```

(`letters.py` can also run alone, for example `./venv/bin/python letters.py --top 5`.)

Read two nightly reports. Check the Applications page: does every row have a sensible score and reason? Open five letters side by side: do they read like five different letters? Check the Inbox page: is every classification right? Correct any that are wrong in the dropdown; your correction is what the tracker uses.

## 4. Schedule it

Install the cron schedule as your user, in local time. The shipped `deploy/crontab` is:

| Stage | Times |
|---|---|
| Discovery (runs scoring and letters after it) | 6:00 AM |
| Submission batch | 8:00 AM |
| Top-up passes (find, score, letter, apply within the day's quota) | 11:00 AM, 2:00 PM, 5:00 PM |
| Inbox triage | 12:00 PM, 6:30 PM |
| Nightly report | 7:00 PM |

```
crontab deploy/crontab
crontab -l
```

Every job checks for `~/jobbot/PAUSE` before doing anything. `touch ~/jobbot/PAUSE` stops the whole system; `rm ~/jobbot/PAUSE` resumes it.

The chat daemon and dashboard services were installed by `install-services.sh` in step 2 (`jobbot-web` and `jobbot-chatd`); `systemctl status jobbot-chatd` confirms the Chat page has a listener.

## 5. Go live, carefully

1. Keep `quota.daily_max` at 10 in `config.json`. Ten good applications beat forty mediocre ones, and the market penalizes volume.
2. Flip `submission.dry_run` to false in `config.json` deliberately. Enable `submission.auto_submit` only after the handoff flow has earned trust.
3. The first twenty live sends each capture a confirmation screenshot. Read every one on the Submissions page before you trust the head.
4. Anything that needs a human (LinkedIn, Indeed, Glassdoor, native forms, CAPTCHAs, unanswered screening questions) lands in the Manual Queue. Clear it from your phone; each card takes about a minute.
5. Raise the quota only after you have read a week of nightly reports.

## 6. Operate

- The Overview page answers "what did it do today, what did it cost, does anything need my hand."
- The Agents page replays the activity log so you can answer "why did it do that" weeks later.
- Interview requests push to your phone through ntfy the moment the reader files them.
- Watch the spend against the cap on the Overview page. The cap is the safety net; the number should stay small.

## 7. Retire it properly

When you are done, the system still holds credentials. Shut it down in this order:

1. `touch ~/jobbot/PAUSE` and `sudo systemctl stop jobbot-chatd jobbot-web`.
2. Pull the nightly CSV export off the container and keep it; the submission history is the most useful artifact.
3. Revoke the API key in the console.
4. Rotate the mailbox password and turn 2FA back on.
5. Take a final Proxmox snapshot, then stop the container.

## Lines you must keep

- Never script LinkedIn, Indeed, Glassdoor, or any board whose terms forbid automation. Route them to a human.
- Never attempt a CAPTCHA or a human-verification wall.
- Never infer export-control or clearance answers.
- Never modify the resume. Mode 444.
- Every application it sends should be one you would have sent by hand.
