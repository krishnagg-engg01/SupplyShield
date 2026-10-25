"""Integration tests against a REAL Exasol instance. Skipped unless connection settings exist and
RUN_EXASOL_INTEGRATION=1 (they only read; they never modify data)."""
import os
import unittest

from supplyshield.config import get_settings
from supplyshield.db import ExasolService
from supplyshield.service import load_from_exasol
from supplyshield import analytics

S = get_settings()
ENABLED = S.configured and os.environ.get("RUN_EXASOL_INTEGRATION") == "1"


@unittest.skipUnless(ENABLED, "set EXASOL_* and RUN_EXASOL_INTEGRATION=1 to run against a real database")
class LiveExasol(unittest.TestCase):
    @classmethod
    def setUpClass(cls): cls.db = ExasolService(S)

    def test_health_check(self): self.assertTrue(self.db.health_check()["ok"])

    def test_views_exist_and_dataset_loads(self):
        ds = load_from_exasol(self.db)
        self.assertTrue(ds["inventory"] and ds["shipments"])

    def test_sql_views_match_python_formulas(self):
        ds = load_from_exasol(self.db)
        raw_hist = self.db.query("SELECT * FROM DELIVERY_HISTORY")
        py = {p["supplier_id"]: p for p in analytics.supplier_performance_from_history(raw_hist)}
        for row in ds["supplier_performance"]:
            self.assertAlmostEqual(row["on_time_rate"], py[row["supplier_id"]]["on_time_rate"], places=3)
            self.assertAlmostEqual(row["avg_delay_days"], py[row["supplier_id"]]["avg_delay_days"], places=1)
        for row in ds["inventory"]:
            exp = analytics.cover_days(row["on_hand_qty"], row["daily_consumption"])
            self.assertTrue((row["cover_days"] is None and exp is None) or abs(row["cover_days"] - exp) < 0.01)


if __name__ == "__main__":
    unittest.main()
