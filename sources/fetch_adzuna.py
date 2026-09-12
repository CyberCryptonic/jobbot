"""Source 3 — Adzuna API. Free tier ~1000 calls/month; we cap at 8/day
(persisted in state.json so multiple runs in one day share the budget).
Salary min/max come structured. redirect_url is resolved later (only for
brand-new rows) by the orchestrator's enrichment pass to classify apply_route.
"""

import urllib.parse

from . import common
from .common import CONFIG, get_json, posting, clean_text

import db


def fetch(run):
    cfg = CONFIG["adzuna"]
    counter = common.CallCounter("adzuna", cfg["daily_call_cap"])
    out, per_query = [], []
    for q in cfg["queries"]:
        if not counter.allow():
            run.log("rate_cap", subject="adzuna", outcome="warn",
                    reason=f"daily call cap {cfg['daily_call_cap']} reached; "
                           f"skipping remaining queries")
            break
        params = {"app_id": db.ENV["ADZUNA_APP_ID"],
                  "app_key": db.ENV["ADZUNA_APP_KEY"],
                  "results_per_page": cfg["results_per_page"],
                  "max_days_old": cfg["max_days_old"],
                  "sort_by": "date"}
        for k in ("what", "what_phrase", "where", "distance"):
            if q.get(k) is not None:
                params[k] = q[k]
        j = get_json("https://api.adzuna.com/v1/api/jobs/us/search/1?"
                     + urllib.parse.urlencode(params))
        counter.tick()
        found_here = 0
        for job in (j or {}).get("results", []):
            company = (job.get("company") or {}).get("display_name")
            title = job.get("title")
            if not company or not title:
                continue
            smin, smax = job.get("salary_min"), job.get("salary_max")
            out.append(dict(posting(
                company, clean_text(title, 200), source="adzuna",
                location=(job.get("location") or {}).get("display_name"),
                job_url=job.get("redirect_url"),
                url_key=f"adzuna:{job.get('id')}",
                posted_date=(job.get("created") or "")[:10] or None,
                salary_posted=(f"${int(smin):,} – ${int(smax):,}"
                               if smin and smax else None),
                salary_min=int(smin) if smin else None,
                salary_max=int(smax) if smax else None,
                apply_route=None,          # resolved post-upsert for new rows
                job_description=clean_text(job.get("description", "")) or None),
                _resolve_route=True))
            found_here += 1
        per_query.append(f"{(q.get('what') or q.get('what_phrase'))[:24]}:{found_here}")
    summary = ("; ".join(per_query)
               + f" | calls today {counter.today_total}/{cfg['daily_call_cap']}")
    return out, counter.calls, summary
