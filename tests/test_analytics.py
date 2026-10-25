import unittest
from datetime import date

from supplyshield import analytics as an
from supplyshield.analytics import ValidationError


class CoverAndStockout(unittest.TestCase):
    def test_cover_days(self):
        self.assertAlmostEqual(an.cover_days(1000, 250), 4.0)

    def test_zero_or_missing_consumption_gives_none(self):
        self.assertIsNone(an.cover_days(1000, 0))
        self.assertIsNone(an.cover_days(1000, None))
        self.assertIsNone(an.cover_days(1000, -5))

    def test_negative_stock_is_floored(self):
        self.assertEqual(an.usable_stock(-40), 0.0)
        self.assertEqual(an.cover_days(-40, 10), 0.0)

    def test_non_numeric_input_rejected(self):
        with self.assertRaises(ValidationError): an.cover_days("abc", 10)
        with self.assertRaises(ValidationError): an.simulate_inventory(100, float("nan"), [])

    def test_stockout_without_inbound(self):
        r = an.simulate_inventory(1000, 100, [], horizon=30)
        self.assertAlmostEqual(r["stockout_in_days"], 10.0)
        self.assertAlmostEqual(r["unmet_units"], 2000.0)
        self.assertFalse(r["recovered"])

    def test_inbound_in_time_prevents_stockout(self):
        r = an.simulate_inventory(1000, 100, [(8, 2000)], horizon=30)
        self.assertIsNone(r["stockout_in_days"]); self.assertEqual(r["recovery_day"], 0)

    def test_inbound_too_late_is_a_gap(self):
        r = an.simulate_inventory(1000, 100, [(15, 5000)], horizon=30)
        self.assertAlmostEqual(r["stockout_in_days"], 10.0)
        self.assertAlmostEqual(r["stockout_days"], 5.0)   # days 10..14 short
        self.assertEqual(r["recovery_day"], 15); self.assertTrue(r["recovered"])

    def test_zero_consumption_never_stocks_out(self):
        r = an.simulate_inventory(0, 0, [], horizon=10)
        self.assertIsNone(r["stockout_in_days"]); self.assertEqual(r["unmet_units"], 0)

    def test_negative_arrival_rejected(self):
        with self.assertRaises(ValidationError): an.simulate_inventory(10, 1, [(1, -5)])

    def test_demand_surge(self):
        r = an.simulate_inventory(1000, 100, [], horizon=10, demand_surge=(2.0, 5))
        self.assertAlmostEqual(r["stockout_in_days"], 5.0)


class SupplierRisk(unittest.TestCase):
    def test_full_data_score(self):
        r = an.supplier_risk_score(0.9, 2, 20, 0.5, 5)
        self.assertEqual(r["missing"], []); self.assertTrue(0 < r["score"] < 100)

    def test_worse_performance_scores_higher(self):
        good = an.supplier_risk_score(0.99, 0, 5, 0.1, 3)["score"]
        bad = an.supplier_risk_score(0.5, 8, 40, 0.9, 3)["score"]
        self.assertGreater(bad, good)

    def test_missing_values_are_renormalised_and_reported(self):
        r = an.supplier_risk_score(on_time_rate=0.8, avg_delay_days=None, lead_time_days=10, capacity_utilisation=None, criticality=4)
        self.assertEqual(set(r["missing"]), {"delay", "capacity"}); self.assertIsNotNone(r["score"]); self.assertLess(r["coverage"], 1)

    def test_too_little_data_gives_no_score(self):
        r = an.supplier_risk_score(on_time_rate=None, avg_delay_days=None, lead_time_days=None, capacity_utilisation=None, criticality=3)
        self.assertIsNone(r["score"]); self.assertEqual(r["band"], "UNKNOWN")

    def test_out_of_range_inputs_are_clamped(self):
        r = an.supplier_risk_score(1.7, -3, 900, 4.0, 9)
        self.assertTrue(0 <= r["score"] <= 100)


class PythonViewEquivalents(unittest.TestCase):
    def test_supplier_performance(self):
        h = [{"supplier_id": "S", "promised_date": date(2026, 1, 1), "actual_date": date(2026, 1, 1)},
             {"supplier_id": "S", "promised_date": date(2026, 1, 1), "actual_date": date(2026, 1, 5)}]
        p = an.supplier_performance_from_history(h)[0]
        self.assertEqual(p["on_time_rate"], 0.5); self.assertEqual(p["avg_delay_days"], 2.0)


if __name__ == "__main__":
    unittest.main()
