"""Source 5 — job-alert emails in the pipeline mailbox (read-only, BODY.PEEK).

Security gates, in order:
  1. Family classification by exact From address / domain (config allowlist).
  2. Authentication-Results check: require dmarc=pass, or spf=pass with the
     From domain on the allowlist. Some providers stamp this header on
     every message; a miss or a fail means the email is skipped and flagged —
     a spoofed alert must not inject jobs into the queue.
  3. Only alert-type subjects are parsed (application confirmations and
     account mail are ignored — they're Layer 7's business).
Link handling: redirects are followed hop-by-hop with a cap, bodies are never
fetched, and Indeed's job key is pulled from the redirect target.
"""

import email
import email.header
import email.policy
import imaplib
import re
import urllib.parse
from datetime import datetime, timedelta

from . import common
from .common import CONFIG, posting, clean_text, resolve_link

import db

CFG = CONFIG["inbox"]

# family -> (from-address regex, alert-subject regex)
ALERT_RULES = {
    "indeed": (r"donotreply@match\.indeed\.com$", r"."),
    "glassdoor": (r"noreply@glassdoor\.com$", r"great fit|apply now"),
    "ziprecruiter": (r"(phil|alerts?|jobalerts?)@([a-z.]*\.)?ziprecruiter\.com$",
                     r"wants your application|new jobs?|jobs? for you|matches"),
    "linkedin": (r"job(alert)?s?-noreply@linkedin\.com$", r"."),
    "jobright": (r"@([a-z.]*\.)?jobright\.ai$", r"match|jobs?|recommend"),
}
FROM_DOMAIN = {"indeed": "indeed.com", "glassdoor": "glassdoor.com",
               "ziprecruiter": "ziprecruiter.com", "linkedin": "linkedin.com",
               "jobright": "jobright.ai"}


def _subject(msg):
    raw = msg["Subject"] or ""
    try:
        return str(email.header.make_header(email.header.decode_header(str(raw))))
    except Exception:
        return str(raw)


def _from_addr(msg):
    m = re.search(r"<([^>]+)>", str(msg["From"] or ""))
    return (m.group(1) if m else str(msg["From"] or "")).strip().lower()


def classify(msg):
    addr = _from_addr(msg)
    subj = _subject(msg).lower()
    for fam, (frx, srx) in ALERT_RULES.items():
        if re.search(frx, addr) and re.search(srx, subj):
            return fam
    return None


def auth_verified(msg, family):
    """dmarc=pass, or spf=pass + allowlisted From domain. Header absent -> fail
    when require_auth_pass is on."""
    ar = " ".join(str(v) for v in (msg.get_all("Authentication-Results") or []))
    if not ar:
        return not CFG["require_auth_pass"]
    ar = ar.lower()
    if "dmarc=pass" in ar:
        return True
    if "spf=pass" in ar and _from_addr(msg).endswith(FROM_DOMAIN[family]):
        return True
    return False


def _parts(msg):
    html = text = ""
    for p in msg.walk():
        ct = p.get_content_type()
        try:
            if ct == "text/html" and not html:
                html = p.get_content()
            elif ct == "text/plain" and not text:
                text = p.get_content()
        except Exception:
            continue
    return html, text


def _text_lines(msg):
    html, text = _parts(msg)
    src = text or re.sub(r"<[^>]+>", "\n", html)
    src = src.replace("&amp;", "&").replace("&#39;", "'").replace("&quot;", '"')
    return [l.strip() for l in src.splitlines() if l.strip()], html


JK_RX = re.compile(r"[?&]jk=([0-9a-f]{8,20})")
SAL_LINE = re.compile(r"\$\s?\d", re.I)
LOC_RX = re.compile(r"^[A-Z][A-Za-z .'-]+,\s?[A-Z]{2}\b|^Remote\b", re.I)


def _indeed_jk(url):
    """jk from the URL itself, else from one capped redirect resolution."""
    m = JK_RX.search(url)
    if m:
        return m.group(1), url
    final, _ = resolve_link(url)
    m = JK_RX.search(final)
    if m:
        return m.group(1), f"https://www.indeed.com/viewjob?jk={m.group(1)}"
    return None, None


def _html_job_links(html):
    """Job-ish hrefs from the HTML part, in document order, deduped.
    HTML hrefs never suffer the text part's line-wrapping."""
    links, seen = [], set()
    for m in re.finditer(
            r'href="(https://(?:cts\.indeed\.com/v3/[^"]+|www\.indeed\.com/(?:pagead/clk|rc/clk|viewjob)[^"]+))"',
            html):
        u = m.group(1).replace("&amp;", "&")
        if u not in seen:
            seen.add(u)
            links.append(u)
    return links


def extract_indeed(msg):
    """Two shapes: single-job match ('Title @ Company' subject, labeled lines)
    and multi-job digest ('Title / Company - Location / $sal' blocks). Links
    come from the HTML part; jk is regexed from the URL or one capped
    redirect resolution."""
    lines, html = _text_lines(msg)
    subj = _subject(msg)
    hlinks = _html_job_links(html)
    out = []

    def mk(title, company, location, salary, urls):
        jk = link = None
        for u in urls[:4]:
            jk, link = _indeed_jk(u)
            if jk:
                break
        if not link and urls:
            link = urls[0]      # board link still opens fine in a browser
        return posting(
            company, title, source="indeed_alert", location=location,
            job_url=link, url_key=f"indeed:{jk}" if jk else None,
            salary_posted=salary, apply_route="native",
            job_description=f"[from Indeed alert email {str(msg['Date'])[:16]}] "
                            + " / ".join(x for x in (title, company, location, salary) if x))

    m1 = re.match(r"^(?:Copy of\s*)?(.+?) @ (.+)$", subj)
    m2 = re.match(r"^(?:Copy of\s*)?(.+?) at (.+?) in (.+?)(?: and \d+ more.*)?$", subj)
    single = m1 or (m2 and "more new" not in subj)

    if single:
        if m1:
            title, company, loc = m1.group(1).strip(), m1.group(2).strip(), None
        else:
            title, company, loc = (m2.group(1).strip(), m2.group(2).strip(),
                                   m2.group(3).strip())
        sal = None
        for i, line in enumerate(lines):
            if line.lower().startswith("salary:"):
                sal = line.split(":", 1)[1].strip()
            elif LOC_RX.match(line) and loc is None and i < 14:
                loc = line
        # prefer the href nearest a 'View job' anchor, else walk candidates
        urls = hlinks
        vm = re.search(r'href="([^"]+)"[^>]*>[^<]{0,40}[Vv]iew job', html)
        if vm:
            urls = [vm.group(1).replace("&amp;", "&")] + hlinks
        out.append(mk(title, company, loc, sal, urls))
        return out

    # digest: field blocks from the text part, links aligned by order from HTML
    job_links = [u for u in hlinks if "pagead/clk" in u or "rc/clk" in u
                 or "viewjob" in u]
    blocks = []
    for i, t in enumerate(lines):
        m = re.match(r"^(.{3,90}?)\s+-\s+([A-Z][A-Za-z .'-]+,\s?[A-Z]{2}|Remote.*)$", t)
        if m and i > 0:
            title = lines[i - 1]
            if re.search(r"privacy|terms|help center|unsubscribe|estimated|indeed",
                         title, re.I):
                continue
            sal = next((s for s in lines[i + 1:i + 4] if SAL_LINE.match(s)), None)
            blocks.append((title, m.group(1), m.group(2), sal))
    for n, (title, company, loc, sal) in enumerate(blocks):
        urls = [job_links[n]] if n < len(job_links) else []
        out.append(mk(title, company, loc, sal, urls))
    return out


GD_SUBJ = re.compile(r"^(.*?) role at (.*?): you would be a great fit", re.I)


def extract_glassdoor(msg):
    subj = _subject(msg)
    m = GD_SUBJ.search(subj)
    if not m:
        return []
    title, company = m.group(1).strip(), m.group(2).strip()
    html, _ = _parts(msg)
    links = re.findall(r'href="(https://www\.glassdoor\.com/partner/jobListing\.htm[^"]+)"', html)
    url = url_key = None
    if links:
        first = links[0].replace("&amp;", "&")
        final, _ = resolve_link(first)
        num = re.search(r"jobListingId=(\d{9,})", final) or re.search(r"(\d{9,})", final)
        if num:
            lid = num.group(1)
            url_key = f"glassdoor:{lid}"
            # stable listing URL reconstructed from the id — the session-bound
            # final hop is worthless once its guid expires
            url = f"https://www.glassdoor.com/partner/jobListing.htm?jobListingId={lid}"
    return [posting(
        company, title, source="glassdoor_alert", job_url=url, url_key=url_key,
        apply_route="native",
        job_description=f"[from Glassdoor alert email {str(msg['Date'])[:16]}] "
                        f"{title} at {company}")]


def extract_ziprecruiter(msg):
    lines, _ = _text_lines(msg)
    out = []
    for i, line in enumerate(lines):
        m = re.match(r"^\*\s*(.{2,80})$", line)
        if not m or i == 0:
            continue
        company = m.group(1).strip()
        if "http" in company or LOC_RX.match(company):
            continue
        # title sits above the company line, skipping link-only lines
        title = None
        for back in range(1, 4):
            if i - back < 0:
                break
            cand = lines[i - back].strip()
            if cand.startswith("<http") or cand.startswith("http") or cand.startswith("*"):
                continue
            title = cand
            break
        if not title or len(title) < 4 or "http" in title:
            continue
        loc = sal = None
        for t in lines[i + 1: i + 6]:
            lm = re.match(r"^\*\s*([A-Z][A-Za-z .'-]+,\s?[A-Z]{2}|\S.*?Remote.*)", t)
            if lm and loc is None:
                loc = lm.group(1).replace("• ", "· ")
            if SAL_LINE.search(t) and sal is None:
                sal = t.lstrip("* ").strip()
        if re.search(r"rooting for you|career advisor", title, re.I):
            continue
        html, _ = _parts(msg)
        km = re.search(r'href="(https://www\.ziprecruiter\.com/km?/[^"]+)"', html)
        out.append(posting(
            company, title, source="ziprecruiter_alert",
            job_url=km.group(1) if km else None,
            location=loc, salary_posted=sal, apply_route="native",
            job_description=f"[from ZipRecruiter alert email {str(msg['Date'])[:16]}] "
                            + " / ".join(x for x in (title, company, loc, sal) if x)))
        break  # invite emails carry exactly one job
    return out


def extract_linkedin(msg):
    """LinkedIn job-alert digests: jobs/view/{id} links with nearby title and
    company text. Written to LinkedIn's documented alert format; validated
    when the first real alert arrives (alerts enabled 2026-08-27)."""
    html, _ = _parts(msg)
    out, seen = [], set()
    for m in re.finditer(
            r'href="https://www\.linkedin\.com/(?:comm/)?jobs/view/(?:[^"]*?-)?(\d{8,12})[^"]*"[^>]*>(.{0,400}?)</a>',
            html, re.S):
        jid, inner = m.group(1), clean_text(m.group(2), 200)
        if jid in seen or not inner or len(inner) < 4:
            continue
        seen.add(jid)
        ctx = clean_text(html[m.end(): m.end() + 500], 200)
        company = loc = None
        cm = re.match(r"^([^·]{2,60})·\s*([^·]{2,60})", ctx)
        if cm:
            company, loc = cm.group(1).strip(), cm.group(2).strip()
        out.append(posting(
            company or "Unknown (LinkedIn alert)", inner,
            source="linkedin_alert", location=loc,
            job_url=f"https://www.linkedin.com/jobs/view/{jid}",
            url_key=f"linkedin:{jid}", apply_route="native",
            job_description=f"[from LinkedIn alert email {str(msg['Date'])[:16]}] {inner}"))
    return out


def extract_jobright(msg):
    """Jobright daily-match emails: jobright.ai/jobs/info/{hex} links.
    Speculative until the first real alert lands (enabled 2026-08-27)."""
    html, _ = _parts(msg)
    out, seen = [], set()
    for m in re.finditer(
            r'href="(https://jobright\.ai/jobs/info/([0-9a-f]{16,32})[^"]*)"[^>]*>(.{0,300}?)</a>',
            html, re.S):
        url, jid, inner = m.group(1), m.group(2), clean_text(m.group(3), 160)
        if jid in seen:
            continue
        seen.add(jid)
        if not inner or len(inner) < 4:
            continue
        title, company = inner, "Unknown (Jobright alert)"
        tm = re.match(r"^(.*?)\s+(?:@|at)\s+(.*)$", inner)
        if tm:
            title, company = tm.group(1), tm.group(2)
        out.append(posting(
            company, title, source="jobright_alert",
            job_url=url.split("?")[0], url_key=f"jobright:{jid}",
            apply_route="native",
            job_description=f"[from Jobright alert email {str(msg['Date'])[:16]}] {inner}"))
    return out


EXTRACTORS = {"indeed": extract_indeed, "glassdoor": extract_glassdoor,
              "ziprecruiter": extract_ziprecruiter, "linkedin": extract_linkedin,
              "jobright": extract_jobright}


def parse_message(msg):
    """(family, verified, postings) — the offline dev harness uses this too."""
    fam = classify(msg)
    if not fam:
        return None, True, []
    if not auth_verified(msg, fam):
        return fam, False, []
    try:
        return fam, True, EXTRACTORS[fam](msg)
    except Exception:
        return fam, True, []


def fetch(run):
    state = common.load_state()
    first = "inbox_last_uid" not in state
    days = CFG["lookback_days_first_run"] if first else CFG["lookback_days"]
    since = (datetime.now(db.TZ) - timedelta(days=days)).strftime("%d-%b-%Y")

    M = imaplib.IMAP4_SSL(db.ENV["MAIL_IMAP_HOST"], int(db.ENV["MAIL_IMAP_PORT"]))
    M.login(db.ENV["MAIL_ADDRESS"], db.ENV["MAIL_PASSWORD"])
    M.select("INBOX", readonly=True)
    typ, d = M.uid("SEARCH", None, "SINCE", since)
    uids = [int(u) for u in d[0].split()]
    last = state.get("inbox_last_uid", 0)
    todo = [u for u in uids if u > last]

    out, per_family, rejected = [], {}, 0
    for uid in todo:
        typ, fd = M.uid("FETCH", str(uid), "(BODY.PEEK[])")
        if typ != "OK" or not fd or fd[0] is None:
            continue
        msg = email.message_from_bytes(fd[0][1], policy=email.policy.default)
        fam, verified, posts = parse_message(msg)
        if fam is None:
            continue
        if not verified:
            rejected += 1
            run.log("sender_rejected", subject=_from_addr(msg), outcome="flag",
                    reason=f"alert-like email failed SPF/DKIM/DMARC verification "
                           f"({fam}); not parsed")
            continue
        out.extend(posts)
        per_family[fam] = per_family.get(fam, 0) + len(posts)
    M.logout()

    if todo:
        state["inbox_last_uid"] = max(todo)
    # first real postings from a previously unproven extractor is a signal the
    # operator asked to see the day it happens
    seen_fams = set(state.get("inbox_families_seen", []))
    for fam, n in sorted(per_family.items()):
        if n > 0 and fam not in seen_fams:
            run.log("extractor_first_result", subject=fam, outcome="ok",
                    reason=f"{fam} alert extractor produced its first real "
                           f"postings ({n}) — extractor validated live")
            seen_fams.add(fam)
    state["inbox_families_seen"] = sorted(seen_fams)
    common.save_state(state)
    summary = "; ".join(f"{k}:{v}" for k, v in sorted(per_family.items())) or "no new alerts"
    if rejected:
        summary += f"; REJECTED unverified: {rejected}"
    return out, len(todo), summary
