"""Source 2 — LinkedIn guest job search endpoint (public, unauthenticated).

Polite by construction: N configured searches, one page each, fixed gap
between requests, hard per-run request cap. Cards parsed from the HTML
fragment; the job id from data-entity-urn is the dedup key. apply_route
defaults to 'native' (Easy Apply unknowable without opening the posting);
about 60% will resolve to ats later at Layer 6's door — routing to the
manual queue is the safe direction for the ambiguous ones.
"""

import re
import urllib.parse

from . import common
from .common import CONFIG, http, posting, clean_text

CARD_RX = re.compile(
    r'data-entity-urn="urn:li:jobPosting:(\d+)".*?'
    r'base-search-card__title[^>]*>\s*(.*?)\s*</h3>.*?'
    r'base-search-card__subtitle[^>]*>.*?<a[^>]*>\s*(.*?)\s*</a>.*?'
    r'job-search-card__location[^>]*>\s*(.*?)\s*</span>'
    r'(?:.*?<time[^>]*datetime="(\d{4}-\d{2}-\d{2})")?',
    re.S)


def fetch(run):
    cfg = CONFIG["linkedin"]
    out, calls = [], 0
    per_search = []
    for s in cfg["searches"]:
        if calls >= cfg["max_requests_per_run"]:
            break
        params = {"keywords": s["keywords"], "location": s["location"],
                  "start": 0, "f_TPR": f"r{cfg['time_window_seconds']}"}
        if s.get("distance"):
            params["distance"] = s["distance"]
        if s.get("remote_only"):
            params["f_WT"] = "2"
        url = ("https://www.linkedin.com/jobs-guest/jobs/api/"
               "seeMoreJobPostings/search?" + urllib.parse.urlencode(params))
        status, raw, _ = http(url, timeout=20)
        calls += 1
        found_here = 0
        if status == 200:
            html = raw.decode("utf-8", "replace")
            for m in CARD_RX.finditer(html):
                jid, title, company, loc, posted = m.groups()
                title = clean_text(title, 200)
                company = clean_text(company, 120)
                if not title or not company:
                    continue
                out.append(posting(
                    company, title, source="linkedin",
                    location=clean_text(loc, 120),
                    job_url=f"https://www.linkedin.com/jobs/view/{jid}",
                    url_key=f"linkedin:{jid}", posted_date=posted,
                    apply_route="native"))
                found_here += 1
        else:
            run.log("fetch_search", subject=f"linkedin: {s['keywords']} @ {s['location']}",
                    outcome="warn", reason=f"HTTP {status} from guest endpoint")
        per_search.append(f"{s['keywords'][:18]}@{s['location'][:12]}:{found_here}")
        common.polite_sleep(cfg["request_gap_seconds"])
    return out, calls, "; ".join(per_search)
