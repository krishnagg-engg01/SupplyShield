"""Application service: data-source modes, dataset loading, dashboard, simulation runs, decisions.

Mode rules (never violated):
  * 'exasol' - every number comes from queries against Exasol.
  * 'demo'   - SYNTHETIC data generated in memory; only entered when the user explicitly chooses it.
  * None     - nothing chosen / connection failed: data endpoints refuse to answer. No silent fallback.
"""
from __future__ import annotations

import json
import threading
import uuid
from datetime import date, datetime, timezone

from . import analytics, scenarios, synthetic
from .analytics import ValidationError
from .config import ASSUMPTIONS, SCORE_WEIGHTS, SQL_DIR, SUPPLIER_RISK_WEIGHTS, ExasolSettings, get_settings
from .db import ExasolError, ExasolService

DECISIONS = ("APPROVED", "REJECTED", "DEFERRED")


class ServiceError(Exception):
    def __init__(self, message: str, status: int = 400, hint: str | None = None, details: list | None = None):
        super().__init__(message)
        self.message, self.status, self.hint, self.details = message, status, hint, details or []


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(microsecond=0, tzinfo=None)


def _iso(dt) -> str | None:
    return dt.isoformat() + "Z" if isinstance(dt, datetime) else None


class AppService:
    def __init__(self, settings: ExasolSettings | None = None, db: ExasolService | None = None):
        self.lock = threading.RLock()
        self.settings = settings or get_settings()
        self.db = db or ExasolService(self.settings)
        self.mode: str | None = None
        self.conn = {"state": "not_configured" if not self.settings.configured else "unknown", "message": "", "last_success_at": None, "latency_ms": None, "kind": None}
        self._data: scenarios.Data | None = None
        self.last_refresh_at: datetime | None = None
        self.demo_runs: list[dict] = []
        self.table_counts: dict | None = None
        if self.settings.configured:
            self.test_connection(auto=True)

    # ------------------------------------------------------------- status / mode
    def reload_settings(self) -> None:
        self.settings = get_settings()
        self.db = ExasolService(self.settings)

    def test_connection(self, auto: bool = False) -> dict:
        with self.lock:
            if not auto:
                self.reload_settings()
            if not self.settings.configured:
                self.conn.update(state="not_configured", message="Missing: " + ", ".join(self.settings.missing()), kind="not_configured")
                if self.mode == "exasol": self.mode, self._data = None, None
                return self.status()
            try:
                res = self.db.health_check()
                self.conn.update(state="connected", message="SELECT 1 succeeded.", last_success_at=_now(), latency_ms=res["latency_ms"], kind=None)
                if self.mode is None:
                    self.mode = "exasol"
                    try:
                        self.refresh()
                    except ServiceError:
                        self.mode, self._data = None, None  # connection state already set to error by refresh()
            except ExasolError as exc:
                self.conn.update(state="error", message=exc.message, kind=exc.kind)
                if self.mode == "exasol": self.mode, self._data = None, None
            return self.status()

    def use_exasol(self) -> dict:
        with self.lock:
            if not self.settings.configured:
                raise ServiceError("Exasol is not configured.", 409, "Set EXASOL_DSN, EXASOL_USER and EXASOL_PASSWORD in your .env file, restart, then retry.")
            prev = (self.mode, self._data)
            self.mode = "exasol"
            try:
                self.refresh()
            except ServiceError:
                self.mode, self._data = None, None
                raise
            return self.status()

    def use_demo(self) -> dict:
        with self.lock:
            self.mode = "demo"
            self._data = scenarios.Data(synthetic.derive(synthetic.build_raw(date.today())))
            self.last_refresh_at = _now()
            self.table_counts = {k: len(v) for k, v in synthetic.build_raw(date.today()).items()}
            return self.status()

    def status(self) -> dict:
        with self.lock:
            if self.mode == "exasol": ui = "connected"
            elif self.mode == "demo": ui = "demo"
            elif self.conn["state"] == "error": ui = "error"
            elif self.conn["state"] == "not_configured": ui = "not_configured"
            else: ui = "idle"
            meta = self._data.meta if self._data else {}
            return {"ui_state": ui, "mode": self.mode,
                    "connection": {"state": self.conn["state"], "message": self.conn["message"], "kind": self.conn["kind"],
                                   "last_success_at": _iso(self.conn["last_success_at"]), "latency_ms": self.conn["latency_ms"]},
                    "settings": self.settings.public(), "last_refresh_at": _iso(self.last_refresh_at),
                    "dataset": {"label": meta.get("label"), "seed": meta.get("seed"), "as_of": meta.get("as_of"), "note": meta.get("note")} if meta else None,
                    "table_counts": self.table_counts}

    # ------------------------------------------------------------- data
    def refresh(self) -> dict:
        with self.lock:
            if self.mode == "exasol":
                try:
                    self._data = scenarios.Data(load_from_exasol(self.db))
                    self.table_counts = self.db.table_counts()
                except ExasolError as exc:
                    self.conn.update(state="error", message=exc.message, kind=exc.kind)
                    raise ServiceError(f"Exasol query failed: {exc.message}", 503, "Fix the connection on the Data Source page, or explicitly switch to the synthetic demo mode.") from exc
                self.conn.update(state="connected", last_success_at=_now(), message="Dataset re-queried.")
                self.last_refresh_at = _now()
            elif self.mode == "demo":
                self.use_demo()
            else:
                raise self._no_source()
            return self.status()

    def _no_source(self) -> ServiceError:
        if self.conn["state"] == "error":
            return ServiceError("Exasol connection error: " + self.conn["message"], 503, "Fix the connection, or explicitly choose the synthetic demo mode. Demo data is never substituted automatically.")
        if self.conn["state"] == "not_configured":
            return ServiceError("No data source is active: Exasol is not configured.", 503, "Add your connection settings to .env, or explicitly choose the synthetic demo mode.")
        return ServiceError("No data source is active.", 503, "Test the Exasol connection or choose the synthetic demo mode.")

    def data(self) -> scenarios.Data:
        with self.lock:
            if self.mode is None: raise self._no_source()
            if self._data is None: self.refresh()
            return self._data  # type: ignore[return-value]

    # ------------------------------------------------------------- dashboard
    def dashboard(self) -> dict:
        d = self.data()
        state = scenarios.base_state(d)
        applied = []
        for ev in d.disruptions:
            if ev["status"] != "OPEN": continue
            req = disruption_to_request(ev)
            if req:
                params = scenarios.validate_params(d, req["scenario"], req["params"])
                scenarios.apply_scenario(d, state, req["scenario"], params)
                applied.append(ev["disruption_id"])
        res = scenarios.summarise(d, state, "open_disruptions", {}, ASSUMPTIONS["default_budget"])
        pairs_all = scenarios.evaluate_pairs(d, state)
        # suppliers
        inbound_sup = {s["supplier"] for s in state["ships"].values()} | set(d.perf)
        sup_rows = sorted((scenarios.supplier_risk(d, s) for s in inbound_sup if s in d.sups), key=lambda r: -(r["score"] if r["score"] is not None else -1))
        for r in sup_rows:
            r["disrupted"] = r["supplier_id"] in state["ctx"]["failed_suppliers"]
        # shipments
        ships = []
        for s in state["ships"].values():
            late = s["cancelled"] or s["eta"] > s["planned"]
            if late:
                ships.append({"shipment_id": s["id"], "supplier_id": s["supplier"], "factory_id": s["factory"], "component_id": s["component"],
                              "qty": s["qty"], "planned_day": s["planned"], "eta_day": None if s["cancelled"] else s["eta"],
                              "delay_days": None if s["cancelled"] else s["eta"] - s["planned"], "status": "CANCELLED" if s["cancelled"] else s["status"]})
        # risk index
        tot_crit = sum(p["criticality"] for p in pairs_all if p.get("assessable"))
        exposed = sum(p["criticality"] for p in pairs_all if p.get("assessable") and p["at_risk"])
        exposure = exposed / tot_crit if tot_crit else 0.0
        inbound_qty = sum(s["qty"] for s in state["ships"].values())
        delayed_qty = sum(s["qty"] for s in state["ships"].values() if s["cancelled"] or s["eta"] > s["planned"])
        delay_share = delayed_qty / inbound_qty if inbound_qty else 0.0
        scored = [r for r in sup_rows if r["score"] is not None and r["open_shipments"] > 0]
        sup_avg = (sum(r["score"] for r in scored) / len(scored)) if scored else None
        parts = {"stockout_exposure": exposure, "supplier_risk": (sup_avg / 100) if sup_avg is not None else None, "inbound_delay_share": delay_share}
        wts = {"stockout_exposure": 0.5, "supplier_risk": 0.3, "inbound_delay_share": 0.2}
        avail = {k: v for k, v in parts.items() if v is not None}
        index = 100 * sum(avail[k] * wts[k] for k in avail) / sum(wts[k] for k in avail)
        band = "LOW" if index < 25 else "MODERATE" if index < 50 else "HIGH" if index < 70 else "CRITICAL"
        # alerts and actions
        alerts = [p for p in pairs_all if p.get("assessable") and (p["at_risk"] or p["below_reorder"] or (p["cover_days"] is not None and p["cover_days"] < 14))]
        actions = []
        for item in res["pairs"]:
            rc = item.get("recovery")
            if not rc: continue
            rec = next((o for o in rc["options"] if o["option_id"] == rc["recommended_id"]), None)
            actions.append({"factory_id": item["factory_id"], "component_id": item["component_id"], "factory": item["factory"], "component": item["component"],
                            "message": rc["message"], "recommended": None if not rec else {"option_id": rec["option_id"], "label": rec["label"], "action_cost": rec["action_cost"],
                            "approval_required": rec["approval"]["required"]}, "stockout_in_days": item["disrupted"]["stockout_in_days"]})
        open_events = []
        for ev in d.disruptions:
            if ev["status"] != "OPEN": continue
            open_events.append({**{k: (v.isoformat() if isinstance(v, (date, datetime)) else v) for k, v in ev.items()},
                                "simulate": disruption_to_request(ev), "applied_in_model": ev["disruption_id"] in applied})
        lines = []
        for item in res["pairs"]:
            for ln in item.get("lines", []):
                lines.append({**ln, "factory": item["factory"], "component": item["component"], "stockout_in_days": item["disrupted"]["stockout_in_days"],
                              "stockout_days": item["disrupted"]["stockout_days"], "lost_output_units": ln["daily_output_units"] * item["disrupted"]["stockout_days"],
                              "loss_cost": ln["daily_output_units"] * ln["margin_per_unit"] * item["disrupted"]["stockout_days"]})
        return {"status": self.status(), "as_of": d.as_of.isoformat(), "applied_disruptions": applied,
                "risk": {"index": round(index, 1), "band": band, "parts": parts, "weights": wts,
                         "explanation": "Index = 100 x (0.5 x criticality-weighted share of positions that run out within the window + 0.3 x average supplier risk of suppliers with open shipments + 0.2 x share of inbound quantity that is late or cancelled). Missing parts are dropped and the other weights re-normalised."},
                "kpis": {"at_risk_positions": res["summary"]["pairs_at_risk"], "total_positions": len(pairs_all),
                         "earliest_stockout_days": res["summary"]["earliest_stockout_days"], "no_action_cost": res["summary"]["no_action_cost"],
                         "cost_complete": res["summary"]["cost_complete"], "expected_recovery_delay_days": res["summary"]["max_recovery_days"],
                         "open_disruptions": d.ds["kpi_counts"]["open_disruptions"], "below_reorder": d.ds["kpi_counts"]["below_reorder_positions"],
                         "delayed_shipments_recorded": d.ds["kpi_counts"]["delayed_shipments"]},
                "positions": pairs_all, "alerts": alerts, "suppliers": sup_rows, "shipments": ships, "lines": lines, "actions": actions,
                "disruptions": open_events, "drivers": res["drivers"], "assumptions": assumptions_payload()}

    # ------------------------------------------------------------- entities
    def entities(self) -> dict:
        d = self.data()
        return {"suppliers": [{"supplier_id": s["supplier_id"], "name": s["name"], "country": s["country"],
                               "components": [c for (sid, c) in d.sc if sid == s["supplier_id"]]} for s in d.ds["suppliers"]],
                "components": [{"component_id": c["component_id"], "name": c["name"]} for c in d.ds["components"]],
                "factories": [{"factory_id": f["factory_id"], "name": f["name"]} for f in d.ds["factories"]],
                "positions": [{"factory_id": f, "component_id": c, "label": f"{d.factories[f]['name']} - {d.comps[c]['name']}"} for (f, c) in d.inv],
                "shipments": [{"shipment_id": s["shipment_id"], "label": f"{s['shipment_id']} - {d.comps[s['component_id']]['name']} to {d.factories[s['factory_id']]['name']} ({d.sups[s['supplier_id']]['name']})"}
                              for s in d.ds["shipments"] if s["status"] in ASSUMPTIONS["inbound_statuses"]],
                "ports": d.ports, "as_of": d.as_of.isoformat(), "default_budget": ASSUMPTIONS["default_budget"]}

    # ------------------------------------------------------------- simulation
    def simulate(self, payload: dict) -> dict:
        d = self.data()
        scenario, params = (payload or {}).get("scenario"), (payload or {}).get("params") or {}
        try:
            result = scenarios.run_scenario(d, scenario, params, payload.get("budget", ASSUMPTIONS["default_budget"]))
        except ValidationError as exc:
            raise ServiceError("Invalid simulation input.", 422, details=exc.errors) from exc
        run_id = "RUN-" + _now().strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:4].upper()
        result.update(run_id=run_id, mode=self.mode, assumptions=assumptions_payload(), persisted=False, persist_error=None)
        self._persist_run(result)
        return result

    def _persist_run(self, result: dict) -> None:
        created = _now()
        summary = {"summary": result["summary"], "recommended": {f"{p['factory_id']}/{p['component_id']}": p["recovery"]["recommended_id"] for p in result["pairs"] if "recovery" in p},
                   "as_of": result["as_of"], "budget": result["budget"]}
        record = {"run_id": result["run_id"], "created_at": created, "scenario_type": result["scenario"], "params": result["params"], "summary": summary,
                  "selected_option": None, "decision": "PENDING", "decided_at": None, "note": None, "mode": self.mode}
        if self.mode == "demo":
            with self.lock:
                self.demo_runs.append(record)
            result["persisted"] = "memory"
            return
        try:
            self.db.insert_rows("scenario_runs", ["run_id", "created_at", "scenario_type", "params_json", "summary_json", "decision"],
                                [(record["run_id"], created, record["scenario_type"], json.dumps(record["params"])[:4000], json.dumps(summary, default=str)[:8000], "PENDING")])
            rows = []
            for p in result["pairs"]:
                rc = p.get("recovery")
                if not rc: continue
                for o in rc["options"]:
                    if not o["feasible"]: continue
                    rows.append((result["run_id"], p["factory_id"], p["component_id"], o["option_id"], o["type"], o["label"][:160], round(o["action_cost"], 2),
                                 round(o["production_loss_cost"] or 0, 2), round(o["total_cost"], 2), round(o["recovery_days"], 1), round(o["stockout_days"], 2),
                                 round(o["unmet_share"], 4), round(o["operational_risk"], 1), o["score"], 1, 1 if o["option_id"] == rc["recommended_id"] else 0,
                                 (o.get("notes") or "")[:600]))
            if rows:
                self.db.insert_rows("recovery_options", ["run_id", "factory_id", "component_id", "option_id", "option_type", "label", "action_cost", "production_loss_cost",
                                                          "total_cost", "recovery_days", "stockout_days", "unmet_share", "operational_risk", "score", "feasible", "is_recommended", "notes"], rows)
            result["persisted"] = "exasol"
        except ExasolError as exc:
            result["persist_error"] = exc.message

    def record_decision(self, run_id: str, payload: dict) -> dict:
        decision = (payload or {}).get("decision")
        option = (payload or {}).get("option_id")
        note = ((payload or {}).get("note") or "")[:500]
        if decision not in DECISIONS:
            raise ServiceError("Invalid decision.", 422, details=[f"decision must be one of {', '.join(DECISIONS)}."])
        if not option or not isinstance(option, str) or len(option) > 40:
            raise ServiceError("Invalid decision.", 422, details=["option_id is required."])
        self.data()
        if self.mode == "demo":
            with self.lock:
                rec = next((r for r in self.demo_runs if r["run_id"] == run_id), None)
                if not rec: raise ServiceError("Unknown run id.", 404)
                rec.update(selected_option=option, decision=decision, decided_at=_now(), note=note)
            return {"ok": True, "stored_in": "memory (demo mode, lost on restart)"}
        try:
            self.db.execute("UPDATE scenario_runs SET selected_option = {o}, decision = {d}, decided_at = {t}, note = {n} WHERE run_id = {r}",
                            {"o": option, "d": decision, "t": _now(), "n": note, "r": run_id})
        except ExasolError as exc:
            raise ServiceError("Could not store the decision in Exasol: " + exc.message, 503) from exc
        return {"ok": True, "stored_in": "Exasol table SCENARIO_RUNS"}

    def runs(self) -> list[dict]:
        self.data()
        if self.mode == "demo":
            return [{"run_id": r["run_id"], "created_at": _iso(r["created_at"]), "scenario_type": r["scenario_type"], "selected_option": r["selected_option"],
                     "decision": r["decision"], "decided_at": _iso(r["decided_at"]), "note": r["note"], "summary": r["summary"], "params": r["params"], "mode": "demo"}
                    for r in reversed(self.demo_runs)]
        try:
            rows = self.db.query("SELECT run_id, created_at, scenario_type, params_json, summary_json, selected_option, decision, decided_at, note FROM scenario_runs ORDER BY created_at DESC LIMIT 50")
        except ExasolError as exc:
            raise ServiceError("Could not read runs from Exasol: " + exc.message, 503) from exc
        return [{**r, "created_at": _iso(r["created_at"]) if isinstance(r["created_at"], datetime) else str(r["created_at"]),
                 "decided_at": _iso(r["decided_at"]) if isinstance(r["decided_at"], datetime) else (str(r["decided_at"]) if r["decided_at"] else None),
                 "params": _loads(r.pop("params_json")), "summary": _loads(r.pop("summary_json")), "mode": "exasol"} for r in rows]


def _loads(s):
    try: return json.loads(s) if s else None
    except ValueError: return None


def assumptions_payload() -> dict:
    return {"assumptions": ASSUMPTIONS, "score_weights": SCORE_WEIGHTS, "supplier_risk_weights": SUPPLIER_RISK_WEIGHTS}


def disruption_to_request(ev: dict) -> dict | None:
    """Map a recorded OPEN disruption to a scenario. Delay / shortage records are informational:
    their effect is already in shipment ETAs and inventory counts, so they are not applied twice."""
    dur = int(ev["duration_days"]) if ev.get("duration_days") else None
    if ev["event_type"] == "SUPPLIER_FAILURE":
        return {"scenario": "supplier_failure", "params": {"supplier_id": ev["entity_id"], "component_id": None, "outage_days": dur or 21, "cancel_open_shipments": False}}
    if ev["event_type"] == "PORT_CLOSURE":
        return {"scenario": "shipment_disruption", "params": {"subtype": "port_closure", "port": ev["entity_id"], "closure_days": dur or 7}}
    return None


# ----------------------------------------------------------------- Exasol loader
def load_from_exasol(db: ExasolService) -> dict:
    """Query the active dataset. Aggregates (cover, supplier performance, commitments, KPI counts) come from SQL views."""
    q = db.query
    ds = {t: q(f"SELECT * FROM {t.upper()}") for t in ("dataset_meta", "components", "suppliers", "supplier_components", "factories", "production_lines",
                                                         "routes", "shipments", "delivery_history", "disruptions")}
    ds["inventory"] = q("SELECT * FROM V_INVENTORY_POSITION")
    ds["supplier_performance"] = q("SELECT * FROM V_SUPPLIER_PERFORMANCE")
    ds["supplier_commitment"] = q("SELECT * FROM V_SUPPLIER_COMMITMENT")
    k = q("SELECT * FROM V_DASHBOARD_KPIS")
    if not k:
        raise ExasolError("V_DASHBOARD_KPIS returned no row. Run scripts/init_db.py.", "schema")
    ds["kpi_counts"] = {key: (float(v) if v is not None else 0) for key, v in k[0].items()}
    for key in ("open_disruptions", "below_reorder_positions", "delayed_shipments"):
        ds["kpi_counts"][key] = int(ds["kpi_counts"][key])
    if not ds["dataset_meta"]:
        raise ExasolError("DATASET_META is empty. Run scripts/seed_db.py (or load your own data).", "schema")
    return normalise_exasol_types(ds)


def normalise_exasol_types(ds: dict) -> dict:
    for rows in ds.values():
        if isinstance(rows, list):
            for r in rows:
                for k, v in list(r.items()):
                    if isinstance(v, datetime) and k.endswith(("_arrival", "_date")): r[k] = v.date()
    return ds
