"""Load the reproducible SYNTHETIC dataset into Exasol (replaces existing seed data).

    python scripts/seed_db.py [--seed 42] [--as-of 2026-10-16]
"""
import argparse
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from supplyshield import synthetic  # noqa: E402
from supplyshield.config import SEED_TABLE_ORDER, TABLE_COLUMNS, get_settings  # noqa: E402
from supplyshield.db import ExasolError, ExasolService  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--seed", type=int, default=synthetic.DEFAULT_SEED)
    ap.add_argument("--as-of", type=date.fromisoformat, default=date.today(), help="reference 'today' for all dates (YYYY-MM-DD)")
    args = ap.parse_args()
    s = get_settings()
    if not s.configured:
        print("Missing settings: " + ", ".join(s.missing())); return 2
    raw = synthetic.build_raw(args.as_of, args.seed)
    problems = synthetic.check_integrity(raw)
    if problems:
        print("Synthetic data failed its own integrity check:\n  " + "\n  ".join(problems)); return 1
    db = ExasolService(s)
    try:
        conn = db._connect()
        try:
            for table in reversed(SEED_TABLE_ORDER):
                conn.execute("DELETE FROM {t!i}", {"t": table.upper()})
            for table in SEED_TABLE_ORDER:
                n = db.insert_rows(table, TABLE_COLUMNS[table], synthetic.table_rows(raw, table), conn=conn)
                print(f"  {table:<20} {n:>4} rows")
        finally:
            db._close(conn)
        print(f"Seeded SYNTHETIC data (seed={args.seed}, as_of={args.as_of}). Scenario history tables were left untouched.")
        return 0
    except (ExasolError, ValueError) as exc:
        print("ERROR: " + getattr(exc, "message", str(exc))); return 1


if __name__ == "__main__":
    sys.exit(main())
