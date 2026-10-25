import unittest

from supplyshield import scenarios as sc, synthetic
from supplyshield.analytics import ValidationError
from tests.helpers import data, raw

SF = {"supplier_id": "S-SZX", "outage_days": 21}


class Propagation(unittest.TestCase):
    def test_supplier_failure_delays_only_undispatched_shipments(self):
        d = data(); r = sc.run_scenario(d, "supplier_failure", {**SF, "cancel_open_shipments": False}, None)
        eff = {x["shipment_id"]: x for x in r["drivers"]}
        self.assertEqual(eff["SH-1001"]["new_eta"], "2026-11-22")      # day 16 + 21
        self.assertNotEqual(eff["SH-1001"]["old_eta"], eff["SH-1001"]["new_eta"])

    def test_in_transit_shipments_are_unaffected(self):
        d = data(lambda r: [s.update(status="IN_TRANSIT") for s in r["shipments"] if s["supplier_id"] == "S-SZX"])
        r = sc.run_scenario(d, "supplier_failure", SF, None)
        self.assertEqual(r["summary"]["pairs_at_risk"], 0)

    def test_failure_cascades_to_stockout_and_line_cost(self):
        r = sc.run_scenario(data(), "supplier_failure", SF, None)
        ids = {(p["factory_id"], p["component_id"]) for p in r["pairs"] if p["at_risk"]}
        self.assertEqual(ids, {("F-CHN", "C-MCU"), ("F-PUN", "C-MCU")})
        chn = next(p for p in r["pairs"] if p["factory_id"] == "F-CHN")
        self.assertAlmostEqual(chn["disrupted"]["stockout_in_days"], 4800 / 260, places=3)
        self.assertAlmostEqual(chn["production_loss_cost"], 260 * 1150 * chn["disrupted"]["stockout_days"], places=2)

    def test_unrelated_positions_are_not_reported(self):
        r = sc.run_scenario(data(), "supplier_failure", SF, None)
        self.assertFalse(any(p["component_id"] == "C-BAT" for p in r["pairs"]))

    def test_cancelled_shipments_remove_supply(self):
        r = sc.run_scenario(data(), "supplier_failure", {**SF, "cancel_open_shipments": True, "outage_days": 1}, None)
        self.assertTrue(r["summary"]["pairs_at_risk"] >= 1)

    def test_port_closure_hits_all_routes_via_port(self):
        r = sc.run_scenario(data(), "shipment_disruption", {"subtype": "port_closure", "port": "Chennai Port", "closure_days": 10}, None)
        hit = {x["shipment_id"] for x in r["drivers"]}
        self.assertTrue({"SH-1001", "SH-1003", "SH-1004", "SH-1011"} <= hit)

    def test_inventory_shortage(self):
        r = sc.run_scenario(data(), "inventory_shortage", {"factory_id": "F-AMD", "component_id": "C-HSG", "stock_loss_pct": 40, "demand_multiplier": 2, "duration_days": 14}, None)
        self.assertEqual([p["component_id"] for p in r["pairs"]], ["C-HSG"]); self.assertTrue(r["pairs"][0]["at_risk"])

    def test_zero_consumption_position_is_not_assessed(self):
        d = data(lambda r: [i.update(daily_consumption=0) for i in r["inventory"] if i["factory_id"] == "F-CHN" and i["component_id"] == "C-MCU"])
        r = sc.run_scenario(d, "supplier_failure", SF, None)
        self.assertTrue(any(x["factory_id"] == "F-CHN" for x in r["assessment_issues"]))


class InvalidInputs(unittest.TestCase):
    def check(self, scenario, params, fragment):
        with self.assertRaises(ValidationError) as cm:
            sc.run_scenario(data(), scenario, params, None)
        self.assertTrue(any(fragment in e for e in cm.exception.errors), cm.exception.errors)

    def test_unknown_scenario(self): self.check("tariff_shock", {}, "Unknown scenario")
    def test_unknown_supplier(self): self.check("supplier_failure", {"supplier_id": "NOPE", "outage_days": 5}, "Select a supplier")
    def test_wrong_component_for_supplier(self): self.check("supplier_failure", {"supplier_id": "S-SZX", "component_id": "C-BAT", "outage_days": 5}, "does not supply")
    def test_negative_days(self): self.check("supplier_failure", {"supplier_id": "S-SZX", "outage_days": -3}, "outage_days")
    def test_non_numeric_days(self): self.check("supplier_failure", {"supplier_id": "S-SZX", "outage_days": "abc"}, "outage_days")
    def test_no_shipments_selected(self): self.check("shipment_disruption", {"subtype": "delay", "delay_days": 3}, "at least one shipment")
    def test_delivered_shipment_rejected(self): self.check("shipment_disruption", {"subtype": "delay", "shipment_ids": ["SH-1010"], "delay_days": 3}, "not inbound")
    def test_unknown_port(self): self.check("shipment_disruption", {"subtype": "port_closure", "port": "Atlantis", "closure_days": 3}, "Select a port")
    def test_no_op_inventory_shock(self): self.check("inventory_shortage", {"factory_id": "F-AMD", "component_id": "C-HSG", "stock_loss_pct": 0, "demand_multiplier": 1}, "nothing changes")
    def test_bad_multiplier(self): self.check("inventory_shortage", {"factory_id": "F-AMD", "component_id": "C-HSG", "stock_loss_pct": 10, "demand_multiplier": 50}, "demand_multiplier")

    def test_all_errors_listed_at_once(self):
        with self.assertRaises(ValidationError) as cm:
            sc.validate_params(data(), "supplier_failure", {"supplier_id": "X", "outage_days": 0})
        self.assertGreaterEqual(len(cm.exception.errors), 2)

    def test_negative_budget(self):
        with self.assertRaises(ValidationError): sc.run_scenario(data(), "supplier_failure", SF, -1)


class RecoveryComparison(unittest.TestCase):
    def setUp(self):
        self.r = sc.run_scenario(data(), "supplier_failure", SF, 500000)
        self.chn = next(p for p in self.r["pairs"] if p["factory_id"] == "F-CHN")["recovery"]
        self.opts = {o["option_id"]: o for o in self.chn["options"]}

    def test_baseline_is_always_present_and_first(self):
        self.assertEqual(self.chn["options"][0]["option_id"], "NO_ACTION")
        self.assertEqual(self.opts["NO_ACTION"]["action_cost"], 0)

    def test_cost_and_delay_differences_vs_baseline(self):
        alt = self.opts["ALT_S-TPE"]
        self.assertAlmostEqual(alt["delta_total_cost"], alt["total_cost"] - self.opts["NO_ACTION"]["total_cost"], places=2)
        self.assertLess(alt["delta_stockout_days"], 0)
        # action cost = qty x (price - standard cost) + setup fee
        qty = alt["inputs"]["qty"]; self.assertAlmostEqual(alt["action_cost"], qty * (455 - 400) + 15000, places=2)

    def test_recommendation_is_the_best_scoring_feasible_option(self):
        self.assertEqual(self.chn["recommended_id"], "ALT_S-TPE")
        scored = {k: o["score"] for k, o in self.opts.items() if o.get("score") is not None}
        self.assertEqual(max(scored, key=scored.get), "ALT_S-TPE")

    def test_capacity_limits_partial_cover(self):
        blr = self.opts["ALT_S-BLR"]
        self.assertAlmostEqual(blr["inputs"]["qty"], 120 * 0.5 * 30)
        self.assertGreater(blr["stockout_days"], 0)

    def test_reallocation_from_a_donor_that_is_also_short_is_excluded(self):
        reasons = " ".join(x["reason"] for x in self.chn["excluded"])
        self.assertIn("Pune Plant is itself projected to run out", reasons)
        self.assertIn("REALLOC_F-AMD", self.opts)

    def test_budget_limit_excludes_expensive_options(self):
        r = sc.run_scenario(data(), "supplier_failure", SF, 100000)
        o = {x["option_id"]: x for x in next(p for p in r["pairs"] if p["factory_id"] == "F-CHN")["recovery"]["options"]}
        self.assertFalse(o["ALT_S-TPE"]["within_budget"]); self.assertIsNone(o["ALT_S-TPE"]["score"]); self.assertIn("exceeds the budget", o["ALT_S-TPE"]["reason"])

    def test_no_confident_recommendation_when_nothing_feasible(self):
        r = sc.run_scenario(data(), "supplier_failure", SF, 0)
        rc = next(p for p in r["pairs"] if p["factory_id"] == "F-CHN")["recovery"]
        self.assertIsNone(rc["recommended_id"]); self.assertIn("no confident recommendation", rc["message"].lower())

    def test_missing_price_data_makes_option_infeasible_not_guessed(self):
        def m(r): [x.update(unit_price=None) for x in r["supplier_components"] if x["supplier_id"] == "S-TPE"]
        r = sc.run_scenario(data(m), "supplier_failure", SF, 500000)
        o = {x["option_id"]: x for x in next(p for p in r["pairs"] if p["factory_id"] == "F-CHN")["recovery"]["options"]}
        self.assertFalse(o["ALT_S-TPE"]["feasible"]); self.assertIn("Missing", o["ALT_S-TPE"]["reason"])
        self.assertNotEqual(next(p for p in r["pairs"] if p["factory_id"] == "F-CHN")["recovery"]["recommended_id"], "ALT_S-TPE")

    def test_single_source_component_is_reported(self):
        d = data(lambda r: r["supplier_components"].__setitem__(slice(None), [x for x in r["supplier_components"] if x["supplier_id"] in ("S-SZX",)]))
        rc = next(p for p in sc.run_scenario(d, "supplier_failure", SF, 500000)["pairs"] if p["factory_id"] == "F-CHN")["recovery"]
        self.assertTrue(any("single-source" in x["reason"] for x in rc["excluded"])); self.assertFalse((rc["recommended_id"] or "").startswith("ALT_"))

    def test_port_closure_offers_reroute_and_expedite(self):
        r = sc.run_scenario(data(), "shipment_disruption", {"subtype": "port_closure", "port": "Chennai Port", "closure_days": 10}, 2_000_000)
        ids = {o["option_id"] for o in next(p for p in r["pairs"] if p["component_id"] == "C-MCU")["recovery"]["options"]}
        self.assertTrue({"REROUTE_R-02", "REROUTE_R-03", "EXPEDITE_SHIPMENTS"} <= ids)

    def test_reroute_never_uses_the_closed_port(self):
        r = sc.run_scenario(data(), "shipment_disruption", {"subtype": "port_closure", "port": "Chennai Port", "closure_days": 10}, 2_000_000)
        for p in r["pairs"]:
            for o in p["recovery"]["options"]:
                if o["type"] == "REROUTE": self.assertNotIn("R-01", o["option_id"]); self.assertNotIn("R-20", o["option_id"])

    def test_deterministic(self):
        again = sc.run_scenario(data(), "supplier_failure", SF, 500000)
        self.assertEqual(self.r["pairs"][0]["recovery"]["recommended_id"], again["pairs"][0]["recovery"]["recommended_id"])
        self.assertEqual(self.r["summary"], again["summary"])


class SyntheticData(unittest.TestCase):
    def test_integrity(self): self.assertEqual(synthetic.check_integrity(raw()), [])
    def test_reproducible(self):
        a, b = raw(), raw(); a["dataset_meta"] = b["dataset_meta"] = None; self.assertEqual(a, b)
    def test_labelled_synthetic(self): self.assertIn(("label", "SYNTHETIC"), [(m["meta_key"], m["meta_value"]) for m in raw()["dataset_meta"]])
    def test_story_exists(self): self.assertTrue(any(d["event_type"] == "SUPPLIER_FAILURE" and d["status"] == "OPEN" for d in raw()["disruptions"]))
    def test_integrity_check_detects_breakage(self):
        r = raw(); r["shipments"][0]["supplier_id"] = "S-GHOST"; self.assertTrue(synthetic.check_integrity(r))


if __name__ == "__main__":
    unittest.main()
