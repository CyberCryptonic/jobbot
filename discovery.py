"""Layer 3 — discovery orchestrator.

Five co-equal sources, each independently toggleable (config.json
sources_enabled), independently logged (one fetch_source row per source per
run with found/new/dupes/calls), and each wrapped in its own try/except so a
single source failing — or returning garbage — never touches the others.

A source that returns zero when its previous run found postings logs a WARN
("went quiet") so a dead feed never masquerades as a slow job market.

Run:  ./venv/bin/python discovery.py                 # all sources + scoring + materials
      ./venv/bin/python discovery.py --source inbox  # one source, no scoring
      ./venv/bin/python discovery.py --no-score
"""

import json
import sys
import time

import db
import materials
import scoring
from sources import common
from sources import fetch_companies, fetch_linkedin, fetch_adzuna, \
    fetch_usajobs, fetch_inbox

SOURCES = [
    ("companies", fetch_companies.fetch),
    ("linkedin", fetch_linkedin.fetch),
    ("adzuna", fetch_adzuna.fetch),
    ("usajobs", fetch_usajobs.fetch),
    ("inbox", fetch_inbox.fetch),
]


def previous_found(conn, source, current_run_id):
    """Most recent found-count for this source from earlier runs (for the
    went-quiet alarm)."""
    rows = conn.execute(
        "SELECT detail FROM activity_log WHERE action='fetch_source' AND subject=? "
        "AND run_id != ? ORDER BY id DESC LIMIT 6",
        (source, current_run_id)).fetchall()
    for r in rows:
        try:
            found = json.loads(r["detail"] or "{}").get("found", 0)
        except ValueError:
            continue
        if found > 0:
            return found
    return None


def ingest(run, conn, source, posts):
    """Upsert postings; enrich brand-new rows that asked for route resolution."""
    new = dupes = resolved = 0
    for p in posts:
        wants_resolve = p.pop("_resolve_route", False)
        app_id, is_new = db.upsert_job(conn, run_id=run.run_id, **p)
        if not is_new:
            dupes += 1
            continue
        new += 1
        if wants_resolve and p.get("job_url"):
            final, hops = common.resolve_link(p["job_url"])
            if common.on_allowed_domain(final):
                route = common.classify_route(final)
                conn.execute(
                    "UPDATE applications SET apply_route=?, job_url=? WHERE id=?",
                    (route, final, app_id))
            else:
                # unexpected destination: keep the original aggregator link,
                # route to the manual queue where human eyes decide
                conn.execute(
                    "UPDATE applications SET apply_route='native' WHERE id=?",
                    (app_id,))
            resolved += 1
    return new, dupes, resolved


def run_discovery(only_source=None):
    enabled = common.CONFIG["sources_enabled"]
    with db.Run("discovery") as run:
        conn = run.conn
        totals = {"found": 0, "new": 0}
        for name, fetcher in SOURCES:
            if only_source and name != only_source:
                continue
            if not enabled.get(name, False):
                run.log("fetch_source", subject=name, outcome="skip",
                        reason="disabled in config.json",
                        detail=json.dumps({"found": None}))
                continue
            t0 = time.monotonic()
            try:
                posts, calls, summary = fetcher(run)
            except Exception as e:
                run.log("fetch_source", subject=name, outcome="fail",
                        duration_ms=int((time.monotonic() - t0) * 1000),
                        reason=f"SOURCE FAILED: {type(e).__name__}: {e}"[:250],
                        detail=json.dumps({"found": 0, "error": str(e)[:300]}))
                continue
            new, dupes, resolved = ingest(run, conn, name, posts)
            dur = int((time.monotonic() - t0) * 1000)
            found = len(posts)
            totals["found"] += found
            totals["new"] += new

            outcome = "ok"
            reason = (f"{found} found, {new} new, {dupes} dupes, {calls} calls"
                      + (f", {resolved} routes resolved" if resolved else "")
                      + (f" — {summary}" if summary else ""))
            if found == 0:
                prev = previous_found(conn, name, run.run_id)
                if prev:
                    outcome = "warn"
                    reason = (f"SOURCE WENT QUIET: 0 found (previous run had "
                              f"{prev}). {calls} calls. Check the feed.")
            run.log("fetch_source", subject=name, outcome=outcome,
                    duration_ms=dur, reason=reason[:400],
                    detail=json.dumps({"found": found, "new": new,
                                       "dupes": dupes, "calls": calls}))
        run.log("discovery_summary",
                reason=f"{totals['found']} postings fetched, {totals['new']} new "
                       f"rows, {totals['found'] - totals['new']} duplicates merged")
    return totals


def enrich_descriptions(limit=40):
    """Fill empty posting text for company-page rows past fetch_companies'
    per-board DETAIL_CAP, using the per-job APIs that need no scraping
    (Greenhouse, Lever). Queued rows first, then by score. One call per row,
    `limit` calls per run. Rows that were scored on title alone keep their
    score (never re-score); the text serves the letter and the next review."""
    from sources.common import clean_text, get_json
    with db.Run("discovery") as run:
        conn = run.conn
        rows = conn.execute(
            "SELECT id, company, role, url_key FROM applications WHERE source='company_page' "
            "AND (job_description IS NULL OR LENGTH(job_description) < 50) "
            "AND (url_key LIKE 'gh:%' OR url_key LIKE 'lever:%') AND status != 'skipped' "
            "ORDER BY (status='queued') DESC, COALESCE(fit_score, -1) DESC, id LIMIT ?", (limit,)).fetchall()
        filled = failed = 0
        for r in rows:
            kind, token, jid = r["url_key"].split(":", 2)
            if kind == "gh":
                j = get_json(f"https://boards-api.greenhouse.io/v1/boards/{token}/jobs/{jid}")
                desc = clean_text((j or {}).get("content", ""))
            else:
                j = get_json(f"https://api.lever.co/v0/postings/{token}/{jid}")
                desc = clean_text((j or {}).get("descriptionPlain") or (j or {}).get("description", ""))
            if desc:
                conn.execute("UPDATE applications SET job_description=?, last_update=? WHERE id=?", (desc, db.now(), r["id"]))
                filled += 1
            else:
                failed += 1
                run.log("enrich_description", subject=f"{r['company']} — {r['role']}", application_id=r["id"],
                        outcome="warn", reason="per-job API returned no text")
            time.sleep(0.5)
        left = conn.execute("SELECT COUNT(*) c FROM applications WHERE source='company_page' "
                            "AND (job_description IS NULL OR LENGTH(job_description) < 50)").fetchone()["c"]
        run.log("enrich_summary", subject=f"{len(rows)} rows",
                reason=f"posting text filled for {filled} company-page rows ({failed} empty replies); "
                       f"{left} company-page rows still have no text (Workday/statejobsny not covered)")
        print(f"enrich: filled {filled}, failed {failed}, still empty {left}")
        return filled


if __name__ == "__main__":
    if db.halt_if_paused("discovery"):
        sys.exit(0)
    if "--enrich" in sys.argv:
        i = sys.argv.index("--enrich")
        n = int(sys.argv[i + 1]) if len(sys.argv) > i + 1 and sys.argv[i + 1].isdigit() else 40
        enrich_descriptions(n)
        sys.exit(0)
    only = None
    if "--source" in sys.argv:
        only = sys.argv[sys.argv.index("--source") + 1]
    t = run_discovery(only)
    if "--no-score" not in sys.argv and only is None:
        try:
            enrich_descriptions(40)      # fill posting text past the per-board detail cap before scoring (operator, 2026-08-29)
        except Exception as e:           # never let enrichment block the day's scoring
            print(f"enrich failed: {type(e).__name__}: {e}", file=sys.stderr)
        scoring.main()
        materials.main([])       # letters, research, screening answers for the queue
    print(f"discovery done: {t}")
