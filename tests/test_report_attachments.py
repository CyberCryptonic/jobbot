"""Review finding #2: the nightly report attaches the small PDF form records
and only the head's confirmation PNGs; filled/blocked PNGs are linked, not
attached; screenshots older than the retention window are pruned."""
import os
import time

import report


def _touch(p, size=10):
    p.write_bytes(b"x" * size)


def test_attachments_pdfs_first_then_confirmed_pngs_only(tmp_path):
    day = tmp_path / "2026-08-29"; day.mkdir()
    for n in ("167-meridian.pdf", "208-graphite.pdf", "167-filled.png", "167-confirmed.png", "169-blocked.png", "170-filled.png"):
        _touch(day / n)
    att = [p.name for p in report.attachments_for(day, 20)]
    assert att == ["167-meridian.pdf", "208-graphite.pdf", "167-confirmed.png"]
    assert [p.name for p in report.attachments_for(day, 2)] == ["167-meridian.pdf", "208-graphite.pdf"]
    assert report.attachments_for(tmp_path / "2026-01-01", 20) == []


def test_prune_screenshots_removes_only_old_day_dirs(tmp_path):
    old = tmp_path / "2026-07-01"; old.mkdir(); _touch(old / "1-filled.png")
    new = tmp_path / "2026-08-29"; new.mkdir(); _touch(new / "2-filled.png")
    stray = tmp_path / "notes.txt"; _touch(stray)
    removed = report.prune_screenshots(tmp_path, keep_days=30, today="2026-08-29")
    assert removed == ["2026-07-01"]
    assert not old.exists() and new.exists() and stray.exists()
    assert report.prune_screenshots(tmp_path, keep_days=30, today="2026-08-29") == []
