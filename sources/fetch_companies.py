"""Source 1 — company career endpoints (ATS public JSON), driven by targets.json.

Supported types: greenhouse, lever, ashby, workday, oracle, statejobsny.
Wide boards are filtered by title regex before any per-job detail call, so one
employer costs 1-3 list calls plus a handful of detail calls at most.
"""

import json
import re
import urllib.parse

from . import common
from .common import BASE_DIR, get_json, http, posting, clean_text

# targets.json is your own company watchlist (gitignored); the shipped
# example keeps a fresh clone importable until you create it.
_targets_file = BASE_DIR / "targets.json"
if not _targets_file.exists():
    _targets_file = BASE_DIR / "targets.example.json"
TARGETS = json.loads(_targets_file.read_text())
TITLE_RX = re.compile(TARGETS["title_filter_default"], re.I)
WD_SEARCHES = ["security", "cyber", "network engineer"]
DETAIL_CAP = 10          # per employer, per run
# statejobsny location filter: set this to the counties/areas you would
# actually commute to (the example covers the capital region + statewide).
STATE_LOC_RX = re.compile(
    r"albany|schenectady|rensselaer|saratoga|statewide|new york city",
    re.I)


def _match(title):
    return bool(title and TITLE_RX.search(title))


def fetch_greenhouse(t, stats):
    j = get_json(f"https://boards-api.greenhouse.io/v1/boards/{t['token']}/jobs?content=false")
    stats["calls"] += 1
    out = []
    for job in (j or {}).get("jobs", []):
        if not _match(job.get("title")):
            continue
        desc = None
        if len(out) < DETAIL_CAP:
            dj = get_json(f"https://boards-api.greenhouse.io/v1/boards/{t['token']}/jobs/{job['id']}")
            stats["calls"] += 1
            if dj:
                desc = clean_text(dj.get("content", ""))
        out.append(posting(
            t["company"], job["title"], source="company_page",
            location=(job.get("location") or {}).get("name"),
            job_url=job.get("absolute_url"),
            url_key=f"gh:{t['token']}:{job['id']}",
            posted_date=(job.get("updated_at") or "")[:10] or None,
            apply_route="ats", job_description=desc))
    return out


def fetch_lever(t, stats):
    out = []
    for skip in (0, 100, 200):
        j = get_json(f"https://api.lever.co/v0/postings/{t['token']}?mode=json&limit=100&skip={skip}")
        stats["calls"] += 1
        if not isinstance(j, list) or not j:
            break
        for job in j:
            title = job.get("text")
            if not _match(title):
                continue
            loc = (job.get("categories") or {}).get("location")
            out.append(posting(
                t["company"], title, source="company_page", location=loc,
                job_url=job.get("hostedUrl"),
                url_key=f"lever:{t['token']}:{job.get('id')}",
                apply_route="ats",
                job_description=clean_text(job.get("descriptionPlain")
                                           or job.get("description", ""))))
        if len(j) < 100:
            break
    return out


def fetch_ashby(t, stats):
    j = get_json(f"https://api.ashbyhq.com/posting-api/job-board/{t['token']}?includeCompensation=true")
    stats["calls"] += 1
    out = []
    for job in (j or {}).get("jobs", []):
        title = job.get("title")
        if not _match(title):
            continue
        comp = job.get("compensation") or {}
        out.append(posting(
            t["company"], title, source="company_page",
            location=job.get("location"),
            job_url=job.get("jobUrl") or job.get("applyUrl"),
            url_key=f"ashby:{t['token']}:{job.get('id')}",
            posted_date=(job.get("publishedAt") or "")[:10] or None,
            salary_posted=comp.get("compensationTierSummary"),
            apply_route="ats",
            job_description=clean_text(job.get("descriptionPlain")
                                       or job.get("descriptionHtml", ""))))
    return out


_WD_AGE = re.compile(r"posted\s+(today|yesterday|(\d+)\+?\s+days?\s+ago)", re.I)


def _wd_posted(text):
    m = _WD_AGE.search(text or "")
    if not m:
        return None
    if m.group(1).lower() == "today":
        return common.days_ago_to_date(0)
    if m.group(1).lower() == "yesterday":
        return common.days_ago_to_date(1)
    return common.days_ago_to_date(int(m.group(2)))


def fetch_workday(t, stats):
    tenant, host, site = t["tenant"], t["host"], t["site"]
    base = f"https://{tenant}.{host}.myworkdayjobs.com"
    cxs = f"{base}/wday/cxs/{tenant}/{site}"
    seen, out = set(), []
    for term in WD_SEARCHES:
        status, raw, _ = http(f"{cxs}/jobs", method="POST",
                              body={"limit": 20, "offset": 0,
                                    "searchText": term, "appliedFacets": {}})
        stats["calls"] += 1
        if status != 200:
            continue
        try:
            jobs = json.loads(raw).get("jobPostings", [])
        except ValueError:
            continue
        for job in jobs:
            path = job.get("externalPath")
            title = job.get("title")
            if not path or path in seen or not _match(title):
                continue
            seen.add(path)
            desc = None
            if len(out) < DETAIL_CAP:
                dj = get_json(f"{cxs}{path}")
                stats["calls"] += 1
                info = (dj or {}).get("jobPostingInfo") or {}
                desc = clean_text(info.get("jobDescription", "")) or None
            out.append(posting(
                t["company"], title, source="company_page",
                location=job.get("locationsText"),
                job_url=f"{base}/en-US/{site}{path}",
                url_key=f"wd:{tenant}:{path.rsplit('_', 1)[-1] if '_' in path else path}",
                posted_date=_wd_posted(job.get("postedOn")),
                apply_route="ats", job_description=desc))
    return out


def fetch_oracle(t, stats):
    base, site = t["base"], t["site_number"]
    kw = urllib.parse.quote('"security"')
    # NOTE: the expand param is load-bearing — Oracle CE returns an empty
    # requisitionList without it.
    url = (f"{base}/hcmRestApi/resources/latest/recruitingCEJobRequisitions"
           f"?onlyData=true&expand=requisitionList.secondaryLocations"
           f"&finder=findReqs;siteNumber={site},limit=50,"
           f"keyword={kw},sortBy=POSTING_DATES_DESC")
    j = get_json(url)
    stats["calls"] += 1
    out = []
    items = (j or {}).get("items") or [{}]
    for req in items[0].get("requisitionList", []):
        title = req.get("Title")
        if not _match(title):
            continue
        rid = req.get("Id")
        out.append(posting(
            t["company"], title, source="company_page",
            location=req.get("PrimaryLocation"),
            job_url=f"{base}/hcmUI/CandidateExperience/en/sites/{site}/job/{rid}",
            url_key=f"oracle:{site}:{rid}",
            posted_date=(req.get("PostedDate") or "")[:10] or None,
            apply_route="ats",
            job_description=clean_text(req.get("ShortDescriptionStr", "")) or None))
    return out


# row: <td>id</td><td><a href=...id=N>title</a></td><td>grade</td>
#      <td>posted mm/dd/yy</td><td>deadline mm/dd/yy</td><td>agency</td><td>county</td>
_SJNY_ROW = re.compile(
    r"vacancyDetailsView\.cfm\?id=(\d+)[^>]*>(.+?)</a>\s*</td>\s*"
    r"<td[^>]*>[^<]*</td>\s*<td[^>]*>([^<]*)</td>\s*<td[^>]*>([^<]*)</td>\s*"
    r"<td[^>]*>([^<]*)</td>\s*<td[^>]*>([^<]*)</td>",
    re.I | re.S)


def _sjny_date(s):
    m = re.match(r"(\d{2})\D(\d{2})\D(\d{2})", clean_text(s, 20))
    return f"20{m.group(3)}-{m.group(1)}-{m.group(2)}" if m else None


def fetch_statejobsny(t, stats):
    status, raw, _ = http("https://statejobsny.com/public/vacancytable.cfm",
                          timeout=25)
    stats["calls"] += 1
    if status != 200:
        return []
    html = raw.decode("utf-8", "replace")
    out = []
    for m in _SJNY_ROW.finditer(html):
        vid = m.group(1)
        title = clean_text(m.group(2), 160)
        posted, deadline = _sjny_date(m.group(3)), _sjny_date(m.group(4))
        agency, county = clean_text(m.group(5), 80), clean_text(m.group(6), 40)
        if not _match(title) or not STATE_LOC_RX.search(county):
            continue
        out.append(posting(
            f"NYS {agency}".strip()[:80], title, source="company_page",
            location=f"{county} County, NY", posted_date=posted,
            job_url=f"https://statejobsny.com/public/vacancyDetailsView.cfm?id={vid}",
            url_key=f"sjny:{vid}", apply_route="native",
            job_description=(f"[NYS civil service — application deadline "
                             f"{deadline}] {title}, {agency}" if deadline else None)))
        if len(out) >= 40:
            break
    return out


FETCHERS = {"greenhouse": fetch_greenhouse, "lever": fetch_lever,
            "ashby": fetch_ashby, "workday": fetch_workday,
            "oracle": fetch_oracle, "statejobsny": fetch_statejobsny}


def fetch(run):
    """Fetch all targets. Per-target failures are logged and skipped — one
    broken employer never takes the source down."""
    all_posts, stats = [], {"calls": 0}
    per_target = []
    for t in TARGETS["targets"]:
        if t.get("enabled") is False:
            continue
        try:
            got = FETCHERS[t["type"]](t, stats)
            all_posts.extend(got)
            per_target.append(f"{t['company']}:{len(got)}")
        except Exception as e:
            run.log("fetch_target", subject=f"{t['company']} ({t['type']})",
                    outcome="warn", reason=f"target failed: {e}"[:200])
    return all_posts, stats["calls"], "; ".join(per_target)
