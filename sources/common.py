"""Shared plumbing for all discovery sources.

Every fetcher returns a list of plain dicts ("postings") with these keys:
    company, role, location, job_url, url_key, source, posted_date,
    salary_posted, salary_min, salary_max, apply_route, job_description
Only company/role/source are required; everything else may be None.
Posting text is untrusted data end to end — nothing here executes or renders
fetched content, and redirects are capped + domain-allowlisted.
"""

import hashlib
import json
import html
import re
import ssl
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import db  # noqa: E402

BASE_DIR = Path(__file__).resolve().parent.parent
CONFIG = json.loads((BASE_DIR / "config.json").read_text())
UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"

STATE_PATH = BASE_DIR / "state.json"


def load_state():
    try:
        return json.loads(STATE_PATH.read_text())
    except (OSError, ValueError):
        return {}


def save_state(state):
    STATE_PATH.write_text(json.dumps(state, indent=1))


class CallCounter:
    """Per-source API call counting with a persisted daily total.

    Enforces daily_call_cap across multiple runs in one day (state.json) and
    exposes .calls for the per-run fetch_source log row.
    """

    def __init__(self, source, daily_cap=None):
        self.source = source
        self.cap = daily_cap
        self.calls = 0
        self.state = load_state()
        day = db.today()
        if self.state.get("call_date") != day:
            self.state["call_date"] = day
            self.state["calls_today"] = {}
        self.today_total = self.state["calls_today"].get(source, 0)

    def allow(self):
        return self.cap is None or (self.today_total + 1) <= self.cap

    def tick(self):
        self.calls += 1
        self.today_total += 1
        self.state["calls_today"][self.source] = self.today_total
        save_state(self.state)


def http(url, *, method="GET", body=None, headers=None, timeout=15):
    """One HTTP request. Returns (status, bytes, final_url); (0, b'', url) on
    network failure. Never raises."""
    h = {"User-Agent": UA, "Accept": "application/json, text/html;q=0.9, */*;q=0.5"}
    if headers:
        h.update(headers)
    data = None
    if body is not None:
        data = body if isinstance(body, bytes) else json.dumps(body).encode()
        h.setdefault("Content-Type", "application/json")
    req = urllib.request.Request(url, data=data, headers=h, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, r.read(8_000_000), r.url
    except urllib.error.HTTPError as e:
        try:
            payload = e.read(100_000)
        except Exception:
            payload = b""
        return e.code, payload, url
    except Exception:
        return 0, b"", url


def get_json(url, **kw):
    status, raw, _ = http(url, **kw)
    if status == 200:
        try:
            return json.loads(raw)
        except ValueError:
            return None
    return None


# ---------------------------------------------------------------------------
# Safe link resolution: follow redirects manually, capped, no bodies fetched,
# final URL must land on an allowlisted domain or we keep the original.
# ---------------------------------------------------------------------------

_RESOLVE_CFG = CONFIG["resolve"]


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **k):
        return None


_no_redirect_opener = urllib.request.build_opener(_NoRedirect)


def domain_of(url):
    try:
        host = urllib.parse.urlparse(url).hostname or ""
    except ValueError:
        return ""
    return host.lower()


def on_allowed_domain(url, extra=()):
    host = domain_of(url)
    for d in list(_RESOLVE_CFG["allowed_final_domains"]) + list(extra):
        if host == d or host.endswith("." + d):
            return True
    return False


def resolve_link(url, max_hops=None):
    """Follow the redirect chain hop by hop using HEAD-style requests without
    ever downloading bodies. Returns (final_url, hops). A hop that fails or
    exceeds the cap returns the last URL seen. Nothing is executed/rendered."""
    hops = 0
    cap = max_hops or _RESOLVE_CFG["max_redirects"]
    current = url
    while hops < cap:
        req = urllib.request.Request(current, method="HEAD",
                                     headers={"User-Agent": UA})
        try:
            resp = _no_redirect_opener.open(
                req, timeout=_RESOLVE_CFG["timeout_seconds"])
            resp.close()
            return current, hops       # 2xx — chain ended here
        except urllib.error.HTTPError as e:
            loc = e.headers.get("Location")
            if e.code in (301, 302, 303, 307, 308) and loc:
                current = urllib.parse.urljoin(current, loc)
                hops += 1
                continue
            return current, hops       # 403/404/... — keep the URL we reached
        except Exception:
            return current, hops
    return current, hops


# ---------------------------------------------------------------------------
# apply_route classification (Layer 6 branches on this)
# ---------------------------------------------------------------------------

ATS_DOMAINS = ("greenhouse.io", "lever.co", "ashbyhq.com", "myworkdayjobs.com",
               "smartrecruiters.com", "workable.com", "icims.com", "taleo.net",
               "oraclecloud.com", "successfactors.com", "jobvite.com",
               "bamboohr.com", "dayforcehcm.com", "ultipro.com", "recruitee.com",
               "teamtailor.com", "breezy.hr", "applytojob.com", "avature.net",
               "eightfold.ai", "paylocity.com", "paycomonline.net")
BOARD_DOMAINS = ("linkedin.com", "indeed.com", "ziprecruiter.com",
                 "glassdoor.com", "jobright.ai", "adzuna.com",
                 "usajobs.gov", "governmentjobs.com", "statejobsny.com")


def classify_route(url):
    """ats = known ATS platform; native = lives on a board / manual portal;
    direct = a company's own domain. None if no URL."""
    if not url:
        return None
    host = domain_of(url)
    for d in ATS_DOMAINS:
        if host == d or host.endswith("." + d):
            return "ats"
    for d in BOARD_DOMAINS:
        if host == d or host.endswith("." + d):
            return "native"
    return "direct"


# ---------------------------------------------------------------------------
# Normalization helpers
# ---------------------------------------------------------------------------

def url_hash_key(url):
    """Fallback url_key: sha1 of the URL minus query junk."""
    if not url:
        return None
    p = urllib.parse.urlparse(url)
    canon = f"{p.netloc.lower()}{p.path}"
    return "url:" + hashlib.sha1(canon.encode()).hexdigest()[:20]


SAL_RX = re.compile(
    r"\$\s?(\d{1,3}(?:,\d{3})*(?:\.\d+)?)\s?(k)?\s*(?:-|–|to)\s*"
    r"\$?\s?(\d{1,3}(?:,\d{3})*(?:\.\d+)?)\s?(k)?", re.I)
SAL_ONE = re.compile(r"\$\s?(\d{1,3}(?:,\d{3})*(?:\.\d+)?)\s?(k)?", re.I)


def parse_salary(text):
    """'$62,000 - $74,000' / '$30 - $35/hr' / '$85k' -> (min, max) yearly ints."""
    if not text:
        return None, None

    def to_year(val, k):
        n = float(val.replace(",", ""))
        if k:
            n *= 1000
        if n < 250:          # hourly
            n *= 2080
        elif n < 20000:      # monthly-ish or weird; leave alone if plausible
            n = n if n > 10000 else n * 2080 / 8  # daily rate fallback
        return int(n)

    m = SAL_RX.search(text)
    if m:
        return to_year(m.group(1), m.group(2)), to_year(m.group(3), m.group(4))
    m = SAL_ONE.search(text)
    if m:
        v = to_year(m.group(1), m.group(2))
        return v, v
    return None, None


def days_ago_to_date(days):
    from datetime import timedelta
    return (datetime.now(db.TZ) - timedelta(days=days)).strftime("%Y-%m-%d")


def clean_text(html_or_text, limit=6000):
    """Strip tags/entities to plain text. For storage only — never rendered."""
    # Greenhouse (and some Workday) boards return the HTML *entity-escaped*
    # (&lt;div&gt;...), so entities are decoded before tags are stripped; a
    # second decode handles text that was escaped once, then tags removed.
    t = html.unescape(html_or_text or "")
    t = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", t, flags=re.S | re.I)
    t = re.sub(r"<[^>]+>", " ", t)
    t = html.unescape(t).replace("\xa0", " ")
    t = re.sub(r"\s+", " ", t).strip()
    return t[:limit]


def posting(company, role, *, source, location=None, job_url=None, url_key=None,
            posted_date=None, salary_posted=None, salary_min=None,
            salary_max=None, apply_route=None, job_description=None):
    if salary_posted and salary_min is None:
        salary_min, salary_max = parse_salary(salary_posted)
    if url_key is None:
        url_key = url_hash_key(job_url)
    if apply_route is None:
        apply_route = classify_route(job_url)
    return {"company": company.strip(), "role": role.strip(),
            "location": (location or "").strip() or None, "source": source,
            "job_url": job_url, "url_key": url_key, "posted_date": posted_date,
            "salary_posted": salary_posted, "salary_min": salary_min,
            "salary_max": salary_max, "apply_route": apply_route,
            "job_description": job_description}


def polite_sleep(seconds):
    time.sleep(seconds)
