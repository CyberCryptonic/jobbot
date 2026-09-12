"""Shared fixtures: every test runs against a throwaway SQLite file, never
jobbot.db. db.DB_PATH is swapped before any stage module opens a connection."""
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "pipeline"))

import db  # noqa: E402
import answers  # noqa: E402

# Tests read the shipped example bank when the operator's real one is absent,
# so a fresh clone can run the suite before config/application-answers.md exists.
if not answers.PATH.exists():
    answers.PATH = ROOT / "config" / "application-answers.example.md"

# A fresh clone has no resume either. Packet builds hash whatever
# db.RESUME_PATH points at, so give tests a small stand-in before the stage
# modules import and freeze the path.
if not db.RESUME_PATH.exists():
    import tempfile
    _resume = Path(tempfile.mkdtemp(prefix="jobbot-tests-")) / "resume.pdf"
    _resume.write_bytes(b"%PDF-1.4\n% test resume stand-in\n%%EOF\n")
    db.RESUME_PATH = _resume


@pytest.fixture
def scratch_db(tmp_path, monkeypatch):
    path = tmp_path / "test.db"
    monkeypatch.setattr(db, "DB_PATH", str(path))
    db.init_db()
    db.migrate()
    conn = db.connect()
    yield conn
    conn.close()


def add_job(conn, company, role, *, location=None, score=None, tier=None,
            route="ats", status="discovered", source="company_page",
            description="x" * 400, url=None):
    jid, _ = db.upsert_job(conn, company=company, role=role, location=location,
                           source=source, job_url=url, job_description=description,
                           apply_route=route)
    conn.execute("UPDATE applications SET fit_score=?, tier=?, status=? WHERE id=?",
                 (score, tier, status, jid))
    return jid


# --- browser tests -------------------------------------------------------------
# tests/.browser-libs (git-ignored) may hold a directory of extracted shared
# libraries for Chromium on a box where `playwright install-deps` has not been
# run. Production never uses this; cron relies on the system libraries.
import os

_libs = ROOT / "tests" / ".browser-libs"
if _libs.exists():
    d = _libs.read_text().strip()
    if d and d not in os.environ.get("LD_LIBRARY_PATH", ""):
        os.environ["LD_LIBRARY_PATH"] = d + (":" + os.environ["LD_LIBRARY_PATH"] if os.environ.get("LD_LIBRARY_PATH") else "")


def pytest_configure(config):
    config.addinivalue_line("markers", "browser: launches headless Chromium (needs its system libraries)")
    config.addinivalue_line("markers", "live: touches a real employer page read-only; run by hand")


@pytest.fixture(scope="session")
def browser_ok():
    """Skip browser tests, loudly, when Chromium cannot start here."""
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            b = p.chromium.launch(headless=True, chromium_sandbox=True)
            b.close()
    except Exception as e:
        pytest.skip(f"Chromium cannot launch here: {str(e).splitlines()[0][:120]} — run: sudo venv/bin/playwright install-deps chromium")
    return True


@pytest.fixture(autouse=True)
def _no_real_notifications(monkeypatch):
    """No test ever sends a real ntfy push or real email. Any code path that
    notifies (code-gate alert, gaps alert, exception push) is stubbed by
    default; tests that assert on a notification re-patch these with their own
    capture, which wins because it is applied inside the test body."""
    import importlib
    for mod, fn in (("notify", "push"), ("mailer", "send")):
        try:
            m = importlib.import_module(mod)
            monkeypatch.setattr(m, fn, lambda *a, **k: True)
        except Exception:
            pass
