import unittest
from datetime import date

from app import create_app
from supplyshield import service as svc_mod, synthetic
from supplyshield.config import ExasolSettings
from supplyshield.db import ExasolError
from supplyshield.service import AppService, ServiceError, load_from_exasol
from tests.helpers import AS_OF, FakeDB

CONF = ExasolSettings(dsn="h:1", user="u", password="p")
SF = {"scenario": "supplier_failure", "params": {"supplier_id": "S-SZX", "outage_days": 21}}


class ModeSeparation(unittest.TestCase):
    def test_unconfigured_never_falls_back_to_demo(self):
        s = AppService(settings=ExasolSettings(), db=FakeDB())
        self.assertEqual(s.status()["ui_state"], "not_configured")
        with self.assertRaises(ServiceError) as cm: s.dashboard()
        self.assertEqual(cm.exception.status, 503); self.assertIsNone(s.mode)

    def test_connection_error_never_falls_back_to_demo(self):
        s = AppService(settings=CONF, db=FakeDB(fail=ExasolError("Could not reach Exasol", "network")))
        self.assertEqual(s.status()["ui_state"], "error")
        for call in (s.dashboard, s.entities, lambda: s.simulate(SF)):
            with self.assertRaises(ServiceError) as cm: call()
            self.assertEqual(cm.exception.status, 503)
        self.assertIsNone(s._data)

    def test_demo_requires_explicit_choice_and_is_labelled(self):
        s = AppService(settings=ExasolSettings(), db=FakeDB()); s.use_demo()
        st = s.status(); self.assertEqual(st["ui_state"], "demo"); self.assertEqual(st["dataset"]["label"], "SYNTHETIC")
        self.assertEqual(s.simulate(SF)["mode"], "demo")

    def test_live_failure_after_connecting_does_not_switch_to_demo(self):
        db = FakeDB(); s = AppService(settings=CONF, db=db); self.assertEqual(s.mode, "exasol")
        db.fail = ExasolError("connection lost", "network")
        with self.assertRaises(ServiceError): s.refresh()
        self.assertEqual(s.conn["state"], "error"); self.assertNotEqual(s.mode, "demo")

    def test_exasol_mode_reports_exasol_and_persists_runs(self):
        db = FakeDB(); s = AppService(settings=CONF, db=db)
        self.assertEqual(s.status()["ui_state"], "connected")
        r = s.simulate(SF); self.assertEqual(r["mode"], "exasol"); self.assertEqual(r["persisted"], "exasol")
        self.assertEqual([t for t, *_ in db.inserted], ["scenario_runs", "recovery_options"])

    def test_persist_failure_is_reported_not_hidden(self):
        db = FakeDB(); s = AppService(settings=CONF, db=db)
        db.insert_rows = lambda *a, **k: (_ for _ in ()).throw(ExasolError("table missing", "query"))
        r = s.simulate(SF); self.assertFalse(r["persisted"]); self.assertEqual(r["persist_error"], "table missing")

    def test_decisions_demo_and_validation(self):
        s = AppService(settings=ExasolSettings(), db=FakeDB()); s.use_demo(); r = s.simulate(SF)
        with self.assertRaises(ServiceError): s.record_decision(r["run_id"], {"decision": "MAYBE", "option_id": "x"})
        with self.assertRaises(ServiceError): s.record_decision("RUN-NOPE", {"decision": "APPROVED", "option_id": "x"})
        out = s.record_decision(r["run_id"], {"decision": "APPROVED", "option_id": "ALT_S-TPE", "note": "ok"})
        self.assertIn("memory", out["stored_in"]); self.assertEqual(s.runs()[0]["decision"], "APPROVED")

    def test_decision_is_parameterised_update_in_exasol(self):
        db = FakeDB(); s = AppService(settings=CONF, db=db)
        s.record_decision("RUN-1", {"decision": "REJECTED", "option_id": "NO_ACTION", "note": "'; DROP TABLE x;--"})
        sql, params = db.executed[-1]; self.assertIn("UPDATE scenario_runs", sql); self.assertNotIn("DROP", sql); self.assertIn("DROP", params["n"])

    def test_invalid_simulation_input_gives_422_with_reasons(self):
        s = AppService(settings=ExasolSettings(), db=FakeDB()); s.use_demo()
        with self.assertRaises(ServiceError) as cm: s.simulate({"scenario": "supplier_failure", "params": {"supplier_id": "?", "outage_days": -1}})
        self.assertEqual(cm.exception.status, 422); self.assertTrue(cm.exception.details)


class DataMapping(unittest.TestCase):
    def test_loader_maps_exasol_rows_to_the_same_dataset_as_demo(self):
        ds = load_from_exasol(FakeDB()); demo = synthetic.derive(synthetic.build_raw(AS_OF))
        for k in ("components", "suppliers", "routes", "shipments", "inventory", "supplier_performance", "kpi_counts"):
            self.assertEqual(ds[k], demo[k], k)

    def test_loader_rejects_empty_database(self):
        db = FakeDB(); db.ds["dataset_meta"] = []
        with self.assertRaises(ExasolError): load_from_exasol(db)

    def test_demo_and_exasol_dashboards_agree_on_identical_data(self):
        db = FakeDB(); live = AppService(settings=CONF, db=db).dashboard()
        self.assertEqual(live["kpis"]["at_risk_positions"], 2); self.assertEqual(live["risk"]["band"], "MODERATE")

    def test_open_disruption_mapping(self):
        self.assertEqual(svc_mod.disruption_to_request({"event_type": "SUPPLIER_FAILURE", "entity_id": "S-X", "duration_days": 9})["params"]["outage_days"], 9)
        self.assertIsNone(svc_mod.disruption_to_request({"event_type": "SHIPMENT_DELAY", "entity_id": "SH-1", "duration_days": 2}))


class Api(unittest.TestCase):
    def client(self, demo=True):
        s = AppService(settings=ExasolSettings(), db=FakeDB())
        if demo: s.use_demo()
        return create_app(s).test_client()

    def test_endpoints_refuse_without_a_source(self):
        c = self.client(demo=False)
        for path in ("/api/dashboard", "/api/entities", "/api/runs"):
            r = c.get(path); self.assertEqual(r.status_code, 503); self.assertIn("hint", r.get_json())

    def test_dashboard_contract(self):
        d = self.client().get("/api/dashboard").get_json()
        for k in ("risk", "kpis", "positions", "suppliers", "shipments", "lines", "actions", "disruptions", "assumptions", "status"): self.assertIn(k, d)
        self.assertEqual(d["status"]["ui_state"], "demo")

    def test_simulate_round_trip_and_bad_input(self):
        c = self.client(); ok = c.post("/api/simulate", json=SF); self.assertEqual(ok.status_code, 200)
        bad = c.post("/api/simulate", json={"scenario": "nope"}); self.assertEqual(bad.status_code, 422)
        self.assertEqual(c.post("/api/simulate", data="not json").status_code, 422)

    def test_status_never_exposes_password(self):
        s = AppService(settings=ExasolSettings(dsn="h:1", user="u", password="topsecret"), db=FakeDB())
        self.assertNotIn("topsecret", create_app(s).test_client().get("/api/status").get_data(as_text=True))

    def test_mode_endpoint_validates(self):
        self.assertEqual(self.client().post("/api/mode", json={"mode": "bogus"}).status_code, 422)


if __name__ == "__main__":
    unittest.main()
