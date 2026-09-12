"""Source 4 — USAJOBS search API (official, keyed, rate-limited per User-Agent).
Federal applications go through the operator's login.gov account, so
apply_route is always 'native' (manual queue). Application deadlines matter
in federal hiring; the close date is prepended to the stored description.
"""

import urllib.parse

from . import common
from .common import CONFIG, get_json, posting, clean_text

import db


def fetch(run):
    cfg = CONFIG["usajobs"]
    counter = common.CallCounter("usajobs", cfg["daily_call_cap"])
    headers = {"Host": "data.usajobs.gov",
               "User-Agent": db.ENV["USAJOBS_EMAIL"],
               "Authorization-Key": db.ENV["USAJOBS_API_KEY"]}
    out, per_query = [], []
    for q in cfg["queries"]:
        if not counter.allow():
            run.log("rate_cap", subject="usajobs", outcome="warn",
                    reason=f"daily call cap {cfg['daily_call_cap']} reached")
            break
        params = dict(q)
        params["ResultsPerPage"] = cfg["results_per_page"]
        j = get_json("https://data.usajobs.gov/api/search?"
                     + urllib.parse.urlencode(params), headers=headers,
                     timeout=25)
        counter.tick()
        found_here = 0
        items = ((j or {}).get("SearchResult") or {}).get("SearchResultItems", [])
        for item in items:
            d = item.get("MatchedObjectDescriptor") or {}
            title = d.get("PositionTitle")
            org = d.get("OrganizationName")
            if not title or not org:
                continue
            locs = d.get("PositionLocationDisplay") or ""
            rem = (d.get("PositionRemuneration") or [{}])[0]
            smin = int(float(rem.get("MinimumRange", 0))) or None
            smax = int(float(rem.get("MaximumRange", 0))) or None
            interval = rem.get("RateIntervalCode", "")
            if interval == "Per Hour":
                smin = int(smin * 2080) if smin else None
                smax = int(smax * 2080) if smax else None
            close = (d.get("ApplicationCloseDate") or "")[:10]
            summary = ((d.get("UserArea") or {}).get("Details") or {}).get("JobSummary", "")
            desc = (f"[Federal — application closes {close}] " if close else "") \
                + clean_text(summary, 5000)
            out.append(posting(
                org, clean_text(title, 200), source="usajobs",
                location=clean_text(locs, 160),
                job_url=d.get("PositionURI"),
                url_key=f"usajobs:{item.get('MatchedObjectId')}",
                posted_date=(d.get("PublicationStartDate") or "")[:10] or None,
                salary_posted=(f"${smin:,} – ${smax:,}" if smin and smax else None),
                salary_min=smin, salary_max=smax,
                apply_route="native", job_description=desc or None))
            found_here += 1
        per_query.append(f"{q.get('Keyword', '?')[:24]}:{found_here}")
    summary = ("; ".join(per_query)
               + f" | calls today {counter.today_total}/{cfg['daily_call_cap']}")
    return out, counter.calls, summary
