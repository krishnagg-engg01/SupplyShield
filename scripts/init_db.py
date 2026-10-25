"""Create the SupplyShield schema, tables and views in Exasol.

    python scripts/init_db.py            # first-time setup (refuses if tables already exist)
    python scripts/init_db.py --reset    # DROP SCHEMA ... CASCADE, then recreate (deletes all data!)
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from supplyshield.config import SQL_DIR, get_settings  # noqa: E402
from supplyshield.db import ExasolError, ExasolService  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--reset", action="store_true", help="drop the schema first (DELETES ALL DATA)")
    args = ap.parse_args()
    s = get_settings()
    if not s.configured:
        print("Missing settings: " + ", ".join(s.missing()) + "\nCopy .env.example to .env and fill in your Exasol connection details."); return 2
    db = ExasolService(s)
    try:
        db.health_check()
        print(f"Connected to Exasol. Target schema: {s.schema}")
        if args.reset:
            c = db._connect(open_schema=False)
            try: c.execute("DROP SCHEMA IF EXISTS {schema!i} CASCADE", {"schema": s.schema})
            finally: db._close(c)
            print("Schema dropped.")
        else:
            c = db._connect(open_schema=False)
            try:
                n = c.execute("SELECT COUNT(*) AS n FROM EXA_ALL_TABLES WHERE TABLE_SCHEMA = {s}", {"s": s.schema}).fetchall()
                n = list(n[0].values())[0] if n else 0
            finally: db._close(c)
            if int(n) > 0:
                print(f"Schema {s.schema} already has {n} tables. Use --reset to recreate (deletes data)."); return 1
        total = 0
        for f in ("01_schema.sql", "02_views.sql"):
            total += db.run_script((SQL_DIR / f).read_text(encoding="utf-8"), create_schema=True)
            print(f"Executed {f}")
        print(f"Done: {total} statements. Next: python scripts/seed_db.py")
        return 0
    except ExasolError as exc:
        print(f"ERROR ({exc.kind}): {exc.message}"); return 1


if __name__ == "__main__":
    sys.exit(main())
