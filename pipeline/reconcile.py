"""One-off tracker reconciliation (Session 8, 2026-08-29).

The inbox backfill created two tracker rows for one application whenever the
Indeed receipt and the employer's own confirmation both arrived, or when a
rejection's company/role text did not match the confirmation's row. This
merges each pair listed in PAIRS into one row:

  1. inbox_messages and activity_log rows of the duplicate are repointed at
     the survivor (history kept);
  2. the survivor gets the duplicate's notes appended and, if the duplicate
     was a rejection, becomes `rejected`;
  3. the duplicate row is deleted, with its full JSON stored in the
     `merge_duplicate` activity row's `detail` so it is recoverable;
  4. one `reconcile_summary` row records before/after counts.

Run on a copy first:  ./venv/bin/python pipeline/reconcile.py --db /path/copy.db
Live:                 ./venv/bin/python pipeline/reconcile.py
"""

import json
import sys
from contextlib import closing

import db

# (survivor, [duplicates], final status or None to keep the survivor's)
PAIRS = [
    (478, [576],      None),        # Confiz: Indeed receipt + employer ATS confirmation
    (585, [584],      None),        # Connective Business Solution: same
    (579, [580],      None),        # MC2: same
    (623, [624],      None),        # Mercor: video-interview mail created a second row
    (653, [660, 661], "rejected"),  # Emergent Staffing: assessment mail + "Emergent Software" rejection
    (507, [693],      "rejected"),  # Teal: Breezy confirmation/action mail vs the Indeed-sourced row that holds the rejection
    (651, [652],      "rejected"),  # Barclays: rejection named the role, confirmation did not
    (602, [608],      "rejected"),  # Coalfire: rejection role text "Vulnerability"
    (587, [588],      "rejected"),  # Harvest Valuations: casing difference
    (667, [668, 672], "rejected"),  # NRI North America: rejections said "NRI"
    (578, [690],      "rejected"),  # Church Pension Group (Services Corporation): prefix mismatch
]
RENAME = {659: "Unknown (Dayforce notice)"}   # company parsed as the literal word "Company"


def counts(conn):
    rows = conn.execute("SELECT status, COUNT(*) n FROM applications GROUP BY status").fetchall()
    c = {r["status"]: r["n"] for r in rows}
    c["distinct_applications"] = sum(v for k, v in c.items()
                                     if k in ("applied", "screening", "interview", "offer", "rejected", "ghosted"))
    return c


def main(argv):
    if "--db" in argv:
        db.DB_PATH = argv[argv.index("--db") + 1]
    with closing(db.connect()) as conn:
        before = counts(conn)
        with db.Run("system", conn=conn) as run:
            for surv_id, dups, final in PAIRS:
                surv = conn.execute("SELECT * FROM applications WHERE id=?", (surv_id,)).fetchone()
                if not surv:
                    run.log("merge_duplicate", subject=f"#{surv_id}", outcome="fail", reason="survivor missing")
                    continue
                for dup_id in dups:
                    dup = conn.execute("SELECT * FROM applications WHERE id=?", (dup_id,)).fetchone()
                    if not dup:
                        run.log("merge_duplicate", subject=f"#{dup_id}", outcome="skip", reason="already gone")
                        continue
                    dupd = dict(dup)
                    uids = [r["uid"] for r in conn.execute(
                        "SELECT uid FROM inbox_messages WHERE application_id=?", (dup_id,))]
                    conn.execute("UPDATE inbox_messages SET application_id=?, "
                                 "match_how=COALESCE(match_how,'') || ' (merged from #' || ? || ')' WHERE application_id=?",
                                 (surv_id, dup_id, dup_id))
                    moved = conn.execute("UPDATE activity_log SET application_id=? WHERE application_id=?",
                                         (surv_id, dup_id)).rowcount
                    note = (f"merged duplicate #{dup_id} ({dup['company']} — {dup['role']}, was {dup['status']}"
                            + (f", applied {dup['date_applied'][:10]}" if dup["date_applied"] else "") + ")"
                            + (f": {dup['notes']}" if dup["notes"] else ""))
                    conn.execute("UPDATE applications SET notes=COALESCE(notes || char(10), '') || ?, "
                                 "date_applied=COALESCE(date_applied, ?), contact_email=COALESCE(contact_email, ?), "
                                 "last_update=? WHERE id=?",
                                 (note, dup["date_applied"], dup["contact_email"], db.now(), surv_id))
                    conn.execute("DELETE FROM applications WHERE id=?", (dup_id,))
                    run.log("merge_duplicate", subject=f"{surv['company']} — {surv['role']}", application_id=surv_id,
                            outcome="warn",
                            reason=f"#{dup_id} {dup['company']} — {dup['role']} ({dup['status']}) merged into #{surv_id}; "
                                   f"{len(uids)} inbox message(s) {uids} and {moved} activity rows repointed",
                            detail=json.dumps({"deleted_row": dupd, "moved_uids": uids, "moved_activity_rows": moved},
                                              default=str))
                    print(f"merged #{dup_id} -> #{surv_id}  ({dup['company']} / {dup['status']}; {len(uids)} msgs)")
                if final and surv["status"] != final:
                    db.set_status(conn, surv_id, final, append_note=f"{surv['status']} → {final}: rejection was on the merged duplicate row")
                    run.log("status_change", subject=f"{surv['company']} — {surv['role']}", application_id=surv_id,
                            outcome="skip", reason=f"{surv['status']} → {final}: rejection had landed on a duplicate row (reconcile)")
                    print(f"   #{surv_id} {surv['status']} -> {final}")
            for app_id, name in RENAME.items():
                r = conn.execute("SELECT company FROM applications WHERE id=?", (app_id,)).fetchone()
                if r and r["company"] != name:
                    conn.execute("UPDATE applications SET company=?, last_update=? WHERE id=?", (name, db.now(), app_id))
                    run.log("company_renamed", subject=f"#{app_id}", application_id=app_id,
                            reason=f"'{r['company']}' → '{name}' (parser took the word Company as the name)")
            after = counts(conn)
            run.log("reconcile_summary", subject="tracker",
                    reason=f"before {json.dumps(before)} → after {json.dumps(after)}",
                    detail=json.dumps({"before": before, "after": after, "pairs": PAIRS}))
        conn.commit()
    print("before:", before)
    print("after: ", after)


if __name__ == "__main__":
    main(sys.argv[1:])
