"""Scenario engine: disruption propagation (supplier -> shipment -> inventory -> production line)
and recovery-option comparison with a transparent score. Pure Python over a dataset dict."""
from __future__ import annotations

import copy
from datetime import date
from typing import Any

from . import analytics
from .analytics import ValidationError, simulate_inventory, supplier_risk_score
from .config import ASSUMPTIONS as A, OPERATIONAL_RISK_BASE, SCORE_WEIGHTS

SCENARIOS = ("supplier_failure", "shipment_disruption", "inventory_shortage")
CHART_DAYS = 45


class Data:
    """Indexed, read-only view of a dataset dict (see synthetic.derive / service loader)."""

    def __init__(self, ds: dict):
        self.ds = ds
        meta = {m["meta_key"]: m["meta_value"] for m in ds.get("dataset_meta", [])}
        self.meta = meta
        self.as_of = date.fromisoformat(meta["as_of"]) if meta.get("as_of") else date.today()
        self.comps = {c["component_id"]: c for c in ds["components"]}
        self.sups = {s["supplier_id"]: s for s in ds["suppliers"]}
        self.sc = {(r["supplier_id"], r["component_id"]): r for r in ds["supplier_components"]}
        self.factories = {f["factory_id"]: f for f in ds["factories"]}
        self.routes = {r["route_id"]: r for r in ds["routes"]}
        self.inv = {(r["factory_id"], r["component_id"]): r for r in ds["inventory"]}
        self.lines: dict[tuple, list] = {}
        for ln in ds["production_lines"]:
            self.lines.setdefault((ln["factory_id"], ln["component_id"]), []).append(ln)
        self.ships = {s["shipment_id"]: s for s in ds["shipments"]}
        self.perf = {p["supplier_id"]: p for p in ds.get("supplier_performance", [])}
        self.commit = {p["supplier_id"]: p for p in ds.get("supplier_commitment", [])}
        self.disruptions = ds.get("disruptions", [])
        self.ports = sorted({r["via_port"] for r in ds["routes"] if r.get("via_port")})

    def off(self, d: date) -> int:
        return (d - self.as_of).days


# ------------------------------------------------------------------ state
def base_state(d: Data) -> dict:
    ships = {}
    for sid, s in d.ships.items():
        if s["status"] not in A["inbound_statuses"]:
            continue
        eta = d.off(s["estimated_arrival"])
        ships[sid] = {"id": sid, "supplier": s["supplier_id"], "factory": s["factory_id"], "component": s["component_id"],
                      "route": s["route_id"], "qty": float(s["quantity"]), "status": s["status"],
                      "planned": d.off(s["planned_arrival"]), "eta0": eta, "eta": eta, "cancelled": False}
    return {"ships": ships, "inv": {}, "drivers": [], "ctx": {"failed_suppliers": set(), "closed_ports": set(), "scenarios": set()}}


def _transit(d: Data, route_id) -> int:
    r = d.routes.get(route_id)
    return int(r["transit_days"]) if r else 0


def _int_in(params: dict, key: str, lo: int, hi: int, errors: list, default=None):
    v = params.get(key, default)
    try:
        iv = float(v)
    except (TypeError, ValueError):
        errors.append(f"{key} must be a number."); return None
    if iv != int(iv) or not (lo <= iv <= hi):
        errors.append(f"{key} must be a whole number between {lo} and {hi}."); return None
    return int(iv)


def validate_params(d: Data, scenario: str, params: dict) -> dict:
    """Return cleaned parameters or raise ValidationError listing every problem."""
    if scenario not in SCENARIOS:
        raise ValidationError(f"Unknown scenario {scenario!r}. Choose one of: {', '.join(SCENARIOS)}.")
    p, errors = params or {}, []
    out: dict[str, Any] = {}
    if scenario == "supplier_failure":
        sid, cid = p.get("supplier_id"), p.get("component_id") or None
        if sid not in d.sups: errors.append("Select a supplier from the list.")
        elif cid and (sid, cid) not in d.sc: errors.append(f"{sid} does not supply {cid}.")
        out = {"supplier_id": sid, "component_id": cid, "outage_days": _int_in(p, "outage_days", 1, 120, errors, 21),
               "cancel_open_shipments": bool(p.get("cancel_open_shipments", False))}
    elif scenario == "shipment_disruption":
        sub = p.get("subtype", "delay")
        if sub == "port_closure":
            if p.get("port") not in d.ports: errors.append("Select a port from the list.")
            out = {"subtype": sub, "port": p.get("port"), "closure_days": _int_in(p, "closure_days", 1, 120, errors, 7)}
        elif sub == "delay":
            ids = p.get("shipment_ids") or []
            if not isinstance(ids, list) or not ids: errors.append("Select at least one shipment.")
            else:
                for i in ids:
                    if i not in d.ships: errors.append(f"Unknown shipment {i}.")
                    elif d.ships[i]["status"] not in A["inbound_statuses"]: errors.append(f"Shipment {i} is not inbound (status {d.ships[i]['status']}).")
            out = {"subtype": sub, "shipment_ids": ids, "delay_days": _int_in(p, "delay_days", 1, 120, errors, 7)}
        else:
            errors.append("subtype must be 'delay' or 'port_closure'.")
    else:
        pair = (p.get("factory_id"), p.get("component_id"))
        if pair not in d.inv: errors.append("Select a factory and a component that has an inventory position.")
        try:
            loss = float(p.get("stock_loss_pct", 0)); mult = float(p.get("demand_multiplier", 1.0))
        except (TypeError, ValueError):
            errors.append("stock_loss_pct and demand_multiplier must be numbers."); loss, mult = 0, 1
        if not (0 <= loss <= 100): errors.append("stock_loss_pct must be between 0 and 100.")
        if not (0.1 <= mult <= 5): errors.append("demand_multiplier must be between 0.1 and 5.")
        if loss == 0 and mult == 1: errors.append("Set a stock loss above 0% or a demand multiplier other than 1.0, otherwise nothing changes.")
        out = {"factory_id": pair[0], "component_id": pair[1], "stock_loss_pct": loss, "demand_multiplier": mult,
               "duration_days": _int_in(p, "duration_days", 1, 60, errors, 14)}
    if errors:
        raise ValidationError(errors)
    return out


def apply_scenario(d: Data, state: dict, scenario: str, p: dict) -> None:
    """Mutate `state` with the cascading first-order effects of one (validated) scenario."""
    ctx = state["ctx"]; ctx["scenarios"].add(scenario)
    def push(ship, new_eta, effect):
        old = ship["eta"]
        ship["eta"] = new_eta
        state["drivers"].append({"shipment_id": ship["id"], "supplier_id": ship["supplier"], "factory_id": ship["factory"],
                                 "component_id": ship["component"], "qty": ship["qty"], "old_eta": old, "new_eta": new_eta, "effect": effect})
    if scenario == "supplier_failure":
        ctx["failed_suppliers"].add(p["supplier_id"])
        for ship in state["ships"].values():
            if ship["supplier"] != p["supplier_id"] or (p["component_id"] and ship["component"] != p["component_id"]):
                continue
            if ship["status"] in ("IN_TRANSIT", "DELAYED"):
                state["drivers"].append({"shipment_id": ship["id"], "supplier_id": ship["supplier"], "factory_id": ship["factory"],
                                         "component_id": ship["component"], "qty": ship["qty"], "old_eta": ship["eta"], "new_eta": ship["eta"],
                                         "effect": "already dispatched - assumed unaffected"})
                continue
            if p["cancel_open_shipments"]:
                ship["cancelled"] = True
                state["drivers"].append({"shipment_id": ship["id"], "supplier_id": ship["supplier"], "factory_id": ship["factory"],
                                         "component_id": ship["component"], "qty": ship["qty"], "old_eta": ship["eta"], "new_eta": None,
                                         "effect": "cancelled (supplier cannot deliver)"})
                continue
            dispatch = max(0, ship["eta"] - _transit(d, ship["route"]))
            delay = max(0, p["outage_days"] - dispatch)
            push(ship, ship["eta"] + delay, f"dispatch held until supplier restarts (day {p['outage_days']}); +{delay} d")
    elif scenario == "shipment_disruption":
        if p["subtype"] == "port_closure":
            ctx["closed_ports"].add(p["port"])
            for ship in state["ships"].values():
                r = d.routes.get(ship["route"])
                if r and r.get("via_port") == p["port"]:
                    push(ship, ship["eta"] + p["closure_days"], f"{p['port']} closed {p['closure_days']} d; +{p['closure_days']} d")
        else:
            for sid in p["shipment_ids"]:
                ship = state["ships"][sid]
                push(ship, ship["eta"] + p["delay_days"], f"delayed +{p['delay_days']} d")
    else:
        pair = (p["factory_id"], p["component_id"])
        mod = state["inv"].setdefault(pair, {"loss_pct": 0.0, "surge": None})
        mod["loss_pct"] = max(mod["loss_pct"], p["stock_loss_pct"])
        if p["demand_multiplier"] != 1:
            mod["surge"] = (p["demand_multiplier"], p["duration_days"])
        state["drivers"].append({"shipment_id": None, "supplier_id": None, "factory_id": pair[0], "component_id": pair[1], "qty": None,
                                 "old_eta": None, "new_eta": None,
                                 "effect": f"stock -{p['stock_loss_pct']:g}%, demand x{p['demand_multiplier']:g} for {p['duration_days']} d"})


# ------------------------------------------------------------------ evaluation
def pair_inputs(d: Data, state: dict, pair: tuple):
    inv = d.inv[pair]
    mod = state["inv"].get(pair, {})
    on_hand = analytics.usable_stock(inv["on_hand_qty"]) * (1 - mod.get("loss_pct", 0) / 100)
    arrivals = [(s["eta"], s["qty"], s["id"]) for s in state["ships"].values()
                if (s["factory"], s["component"]) == pair and not s["cancelled"]]
    return on_hand, float(inv["daily_consumption"] or 0), arrivals, mod.get("surge")


def _sim(on_hand, daily, arrivals, surge=None, extra=()):
    return simulate_inventory(on_hand, daily, [(a[0], a[1]) for a in arrivals] + [(e[0], e[1]) for e in extra], demand_surge=surge)


def production_loss(d: Data, pair: tuple, stockout_days: float) -> tuple[float | None, float | None]:
    lines = d.lines.get(pair)
    if not lines:
        return None, None
    units = sum(float(l["daily_output_units"]) * stockout_days for l in lines)
    cost = sum(float(l["daily_output_units"]) * float(l["margin_per_unit"]) * stockout_days for l in lines)
    return units, cost


def _slim(sim: dict) -> dict:
    return {k: v for k, v in sim.items() if k != "series"}


def evaluate_pairs(d: Data, state: dict) -> list[dict]:
    base = base_state(d)
    out = []
    for pair, inv in d.inv.items():
        daily = float(inv["daily_consumption"] or 0)
        entry = {"factory_id": pair[0], "component_id": pair[1], "component": d.comps[pair[1]]["name"],
                 "factory": d.factories[pair[0]]["name"], "criticality": d.comps[pair[1]]["criticality"], "daily_consumption": daily,
                 "on_hand": float(inv["on_hand_qty"]), "usable_stock": analytics.usable_stock(inv["on_hand_qty"]),
                 "cover_days": analytics.cover_days(inv["on_hand_qty"], daily), "reorder_point": float(inv["reorder_point_qty"]),
                 "safety_stock": float(inv["safety_stock_qty"]), "below_reorder": float(inv["on_hand_qty"]) <= float(inv["reorder_point_qty"])}
        if daily <= 0:
            entry.update(assessable=False, reason="Daily consumption is zero or missing, so cover and stockout cannot be estimated.",
                         affected=False, at_risk=False)
            out.append(entry); continue
        b_oh, _, b_arr, b_surge = pair_inputs(d, base, pair)
        s_oh, _, s_arr, s_surge = pair_inputs(d, state, pair)
        b_sim, s_sim = _sim(b_oh, daily, b_arr, b_surge), _sim(s_oh, daily, s_arr, s_surge)
        affected = (sorted((a[0], a[1]) for a in b_arr) != sorted((a[0], a[1]) for a in s_arr)) or pair in state["inv"]
        loss_units, loss_cost = production_loss(d, pair, s_sim["stockout_days"])
        b_units, b_cost = production_loss(d, pair, b_sim["stockout_days"])
        entry.update(assessable=True, affected=affected, at_risk=s_sim["stockout_in_days"] is not None,
                     baseline=_slim(b_sim), disrupted=_slim(s_sim), series_baseline=b_sim["series"][:CHART_DAYS],
                     series_disrupted=s_sim["series"][:CHART_DAYS], production_loss_units=loss_units, production_loss_cost=loss_cost,
                     baseline_loss_cost=b_cost, lines=[{"line_id": l["line_id"], "name": l["name"], "daily_output_units": float(l["daily_output_units"]),
                                                       "margin_per_unit": float(l["margin_per_unit"])} for l in d.lines.get(pair, [])],
                     arrivals=[{"shipment_id": a[2], "eta": a[0], "qty": a[1]} for a in sorted(s_arr)],
                     missing_line_mapping=pair not in d.lines)
        out.append(entry)
    return out


# ------------------------------------------------------------------ supplier risk
def supplier_risk(d: Data, supplier_id: str) -> dict:
    perf = d.perf.get(supplier_id)
    offers = [r for (s, c), r in d.sc.items() if s == supplier_id]
    lead = (sum(float(o["lead_time_days"]) for o in offers) / len(offers)) if offers else None
    cap = sum(float(o["capacity_per_day"]) for o in offers) * A["alt_surge_window_days"] if offers else 0
    open_qty = float(d.commit.get(supplier_id, {}).get("open_qty", 0) or 0)
    util = (open_qty / cap) if cap > 0 else None
    crit = max((d.comps[o["component_id"]]["criticality"] for o in offers if o["component_id"] in d.comps), default=None)
    res = supplier_risk_score(perf["on_time_rate"] if perf else None, perf["avg_delay_days"] if perf else None, lead, util, crit)
    res.update(supplier_id=supplier_id, name=d.sups[supplier_id]["name"], on_time_rate=perf["on_time_rate"] if perf else None,
               avg_delay_days=perf["avg_delay_days"] if perf else None, lead_time_days=lead, capacity_utilisation=util,
               open_shipments=int(d.commit.get(supplier_id, {}).get("open_shipments", 0) or 0), open_qty=open_qty)
    return res


# ------------------------------------------------------------------ recovery options
def _approval(opt_type: str, action_cost: float) -> dict:
    if action_cost > A["approval_threshold"]:
        return {"required": True, "reason": f"Action cost above the INR {A['approval_threshold']:,.0f} policy threshold."}
    if opt_type == "ALT_SUPPLIER":
        return {"required": True, "reason": "Onboarding a different supplier always needs buyer / quality sign-off."}
    return {"required": False, "reason": "Within threshold: planner review only. SupplyShield never places orders."}


def build_options(d: Data, state: dict, pe: dict, budget: float | None) -> dict:
    """Generate, evaluate and score recovery options for one at-risk factory/component pair."""
    pair = (pe["factory_id"], pe["component_id"])
    comp = d.comps[pair[1]]
    oh, daily, arrivals, surge = pair_inputs(d, state, pair)
    base = pe["disrupted"]
    unmet = base["unmet_units"]
    ctx = state["ctx"]
    affected = [s for s in state["ships"].values() if (s["factory"], s["component"]) == pair and (s["eta"] != s["eta0"] or s["cancelled"])]
    excluded: list[dict] = []
    unit_cost = float(comp["unit_cost"]) if comp.get("unit_cost") is not None else None
    cands: list[dict] = []

    def evaluate(opt: dict, extra=(), arr=None, onhand_adj=0.0, stress_delay=0) -> dict:
        arr = arrivals if arr is None else arr
        sim = _sim(oh + onhand_adj, daily, arr, surge, extra)
        stress = _sim(oh + onhand_adj, daily, arr, surge, [(e[0] + stress_delay, e[1]) for e in extra]) if extra else sim
        lu, lc = production_loss(d, pair, sim["stockout_days"])
        opt.update(feasible=True, sim=_slim(sim), series=sim["series"][:CHART_DAYS], stockout_days=sim["stockout_days"],
                   unmet_share=sim["unmet_share"], recovery_days=sim["recovery_day"], recovered=sim["recovered"],
                   production_loss_units=lu, production_loss_cost=lc, stress_stockout_days=stress["stockout_days"],
                   stress_delay_days=stress_delay)
        opt["total_cost"] = opt["action_cost"] + (lc or 0.0)
        opt["approval"] = _approval(opt["type"], opt["action_cost"])
        return opt

    def infeasible(opt_id, typ, label, reason):
        return {"option_id": opt_id, "type": typ, "label": label, "feasible": False, "reason": reason, "action_cost": 0.0, "operational_risk": None}

    # 0. baseline
    lu, lc = production_loss(d, pair, base["stockout_days"])
    baseline = {"option_id": "NO_ACTION", "type": "NO_ACTION", "label": "No action - wait for the original supplier / shipment",
                "action_cost": 0.0, "operational_risk": OPERATIONAL_RISK_BASE["NO_ACTION"], "feasible": True, "sim": _slim(base),
                "series": pe["series_disrupted"], "stockout_days": base["stockout_days"], "unmet_share": base["unmet_share"],
                "recovery_days": base["recovery_day"], "recovered": base["recovered"], "production_loss_units": lu, "production_loss_cost": lc,
                "total_cost": (lc or 0.0), "stress_stockout_days": base["stockout_days"], "stress_delay_days": 0,
                "approval": {"required": False, "reason": "Baseline: no change to operations."},
                "notes": "Production loss uses margin per unit on the lines fed by this component."}
    cands.append(baseline)

    # 1. alternative supplier
    shipments_here = {s["supplier"] for s in state["ships"].values() if (s["factory"], s["component"]) == pair}
    skip = set(ctx["failed_suppliers"]) | {s["supplier"] for s in affected}
    if "inventory_shortage" in ctx["scenarios"] and not affected:
        skip |= shipments_here
    alts = sorted([r for (sid, cid), r in d.sc.items() if cid == pair[1] and sid not in skip and d.sups[sid]["status"] == "ACTIVE"],
                  key=lambda r: float(r["lead_time_days"]))
    if not alts:
        excluded.append({"type": "ALT_SUPPLIER", "reason": f"No other active supplier is on file for {comp['name']} (single-source component)."})
    for r in alts[:3]:
        sid = r["supplier_id"]; oid = f"ALT_{sid}"
        label = f"Buy from alternative supplier {d.sups[sid]['name']}"
        price, lead, cap = r.get("unit_price"), r.get("lead_time_days"), r.get("capacity_per_day")
        if price is None or lead is None or not cap or float(cap) <= 0 or unit_cost is None:
            cands.append(infeasible(oid, "ALT_SUPPLIER", label, "Missing price, lead time, capacity or unit cost - cannot evaluate.")); continue
        max_qty = float(cap) * A["alt_surge_share"] * A["alt_surge_window_days"]
        qty = min(unmet, max_qty)
        cost = qty * max(0.0, float(price) - unit_cost) + A["alt_setup_fee"]
        perf = d.perf.get(sid)
        stress = int(round(perf["avg_delay_days"])) if perf and perf.get("avg_delay_days") is not None else 3
        risk = supplier_risk(d, sid)
        op_risk = OPERATIONAL_RISK_BASE["ALT_SUPPLIER"] if risk["score"] is None else 0.5 * OPERATIONAL_RISK_BASE["ALT_SUPPLIER"] + 0.5 * risk["score"]
        opt = {"option_id": oid, "type": "ALT_SUPPLIER", "label": label, "action_cost": cost, "operational_risk": op_risk,
               "notes": f"Order {qty:,.0f} pcs (cap {max_qty:,.0f} = {A['alt_surge_share']:.0%} of {float(cap):,.0f}/day x {A['alt_surge_window_days']} d), "
                        f"arrives day {int(lead)}. Cost = qty x (price {float(price):,.0f} - standard {unit_cost:,.0f}) + setup fee. "
                        f"Supplier risk score {risk['score'] if risk['score'] is not None else 'n/a'}."
                        + ("" if perf else " No delivery history for this supplier - stress delay assumed 3 d."),
               "inputs": {"supplier_id": sid, "qty": qty, "arrival_day": int(lead), "unit_price": float(price)}}
        evaluate(opt, extra=[(int(lead), qty)], stress_delay=stress)
        if qty < unmet: opt["notes"] += f" Covers only part of the {unmet:,.0f}-pc shortfall."
        cands.append(opt)

    # 2. reroute (shipment disruptions only)
    if "shipment_disruption" in ctx["scenarios"] and affected:
        groups: dict[str, list] = {}
        for s in affected:
            if s["cancelled"] or s["route"] not in d.routes: continue
            cur, region = d.routes[s["route"]], d.sups[s["supplier"]]["region"]
            for rid, r in d.routes.items():
                if (rid != s["route"] and r["destination_factory_id"] == pair[0] and r["origin_region"] == region and r["status"] == "OPEN"
                        and r.get("via_port") not in ctx["closed_ports"]):
                    new_eta = max(0, s["eta0"] - int(cur["transit_days"])) + int(r["transit_days"]) + A["reroute_handling_days"]
                    if new_eta < s["eta"]:
                        groups.setdefault(rid, []).append((s, new_eta, max(0.0, float(r["cost_per_unit"]) - float(cur["cost_per_unit"]))))
        for rid, items in groups.items():
            r = d.routes[rid]; new = {s["id"]: ne for s, ne, _ in items}
            cost = sum(s["qty"] * extra for s, _, extra in items) + A["reroute_fixed_fee"]
            arr = [(new.get(a[2], a[0]), a[1], a[2]) for a in arrivals]
            opt = {"option_id": f"REROUTE_{rid}", "type": "REROUTE", "label": f"Reroute {len(items)} shipment(s): {r['name']}", "action_cost": cost,
                   "operational_risk": float(OPERATIONAL_RISK_BASE["REROUTE"]) + (10 if r["mode"] == "AIR" else 0),
                   "notes": "New ETA = dispatch day + route transit + %d d re-booking. Freight cost = qty x (new - current cost/unit) + fixed fee. Shipments: %s." % (
                       A["reroute_handling_days"], ", ".join(f"{s['id']} -> day {ne}" for s, ne, _ in items)),
                   "inputs": {"route_id": rid, "shipments": list(new)}}
            evaluate(opt, arr=arr); cands.append(opt)
        if not groups:
            excluded.append({"type": "REROUTE", "reason": "No open alternative route into this factory arrives earlier than the disrupted ETA."})
    else:
        excluded.append({"type": "REROUTE", "reason": "Not applicable: no shipment delay or port closure in this scenario (a failed supplier cannot dispatch on any route)."
                         if "supplier_failure" in ctx["scenarios"] else "Not applicable: no delayed shipment feeds this position."})

    # 3. reallocate between factories
    donors = []
    for (f2, c2), inv2 in d.inv.items():
        if c2 != pair[1] or f2 == pair[0]: continue
        dnr = next((x for x in evaluate_pairs_cached(d, state) if (x["factory_id"], x["component_id"]) == (f2, c2)), None)
        name = d.factories[f2]["name"]
        if not dnr or not dnr.get("assessable"):
            excluded.append({"type": "REALLOCATE", "reason": f"{name}: donor consumption data missing."}); continue
        if dnr["at_risk"]:
            excluded.append({"type": "REALLOCATE", "reason": f"{name} is itself projected to run out of {comp['name']} - moving stock would only move the shortage."}); continue
        keep = max(float(inv2["safety_stock_qty"]), float(inv2["daily_consumption"]) * A["donor_min_cover_days"])
        spare = max(0.0, analytics.usable_stock(inv2["on_hand_qty"]) - keep)
        if spare <= 0:
            excluded.append({"type": "REALLOCATE", "reason": f"{name} has no stock above its safety stock / {A['donor_min_cover_days']}-day cover."}); continue
        donors.append((f2, spare, keep))
    for f2, spare, keep in donors:
        if unit_cost is None:
            cands.append(infeasible(f"REALLOC_{f2}", "REALLOCATE", f"Transfer from {d.factories[f2]['name']}", "Missing unit cost.")); continue
        qty = min(spare, unmet)
        cost = qty * unit_cost * A["transfer_cost_pct_of_unit_cost"] + A["transfer_fixed_fee"]
        d_oh, d_daily, d_arr, d_surge = pair_inputs(d, state, (f2, pair[1]))
        d_sim = _sim(d_oh - qty, d_daily, d_arr, d_surge)
        opt = {"option_id": f"REALLOC_{f2}", "type": "REALLOCATE", "label": f"Transfer stock from {d.factories[f2]['name']}", "action_cost": cost,
               "operational_risk": min(100.0, OPERATIONAL_RISK_BASE["REALLOCATE"] + 15 * d_sim["stockout_days"]),
               "notes": f"Move {qty:,.0f} pcs (spare above donor reserve {keep:,.0f}) in {A['transfer_days']} d. Cost = qty x standard cost x "
                        f"{A['transfer_cost_pct_of_unit_cost']:.0%} + fixed fee. Donor stockout days after transfer: {d_sim['stockout_days']:.1f}.",
               "inputs": {"from_factory": f2, "qty": qty}}
        evaluate(opt, extra=[(A["transfer_days"], qty)])
        if qty < unmet: opt["notes"] += f" Covers only part of the {unmet:,.0f}-pc shortfall."
        cands.append(opt)

    # 4. expedite
    if affected and "shipment_disruption" in ctx["scenarios"] and unit_cost is not None:
        new = {}
        for s in affected:
            if s["cancelled"]: continue
            added = s["eta"] - s["eta0"]
            new[s["id"]] = s["eta0"] + int(round(added * (1 - A["expedite_delay_reduction"])))
        cost = sum(state["ships"][i]["qty"] for i in new) * unit_cost * A["expedite_air_premium_pct"]
        arr = [(new.get(a[2], a[0]), a[1], a[2]) for a in arrivals]
        opt = {"option_id": "EXPEDITE_SHIPMENTS", "type": "EXPEDITE", "label": "Expedite the delayed shipments (air / priority handling)", "action_cost": cost,
               "operational_risk": OPERATIONAL_RISK_BASE["EXPEDITE"],
               "notes": f"Assumes {A['expedite_delay_reduction']:.0%} of the added delay is recovered; cost = qty x standard cost x {A['expedite_air_premium_pct']:.0%} premium.",
               "inputs": {"shipments": list(new)}}
        evaluate(opt, arr=arr); cands.append(opt)
    elif "inventory_shortage" in ctx["scenarios"] and not affected and unit_cost is not None:
        inc = sorted([r for (sid, cid), r in d.sc.items() if cid == pair[1] and sid in shipments_here and sid not in ctx["failed_suppliers"]],
                     key=lambda r: float(r["lead_time_days"]))
        if not inc:
            excluded.append({"type": "EXPEDITE", "reason": "No incumbent supplier with price and lead-time data to place an expedited order with."})
        for r in inc[:1]:
            sid = r["supplier_id"]; lead = max(1, int(round(float(r["lead_time_days"]) * A["expedite_order_lead_factor"])))
            qty = min(unmet, float(r["capacity_per_day"]) * A["alt_surge_share"] * A["alt_surge_window_days"])
            cost = qty * max(0.0, float(r["unit_price"]) * (1 + A["expedite_order_price_premium"]) - unit_cost)
            perf = d.perf.get(sid)
            opt = {"option_id": f"EXPEDITE_{sid}", "type": "EXPEDITE", "label": f"Expedite a replenishment order with {d.sups[sid]['name']}", "action_cost": cost,
                   "operational_risk": OPERATIONAL_RISK_BASE["EXPEDITE"],
                   "notes": f"Order {qty:,.0f} pcs, lead time halved to {lead} d, price +{A['expedite_order_price_premium']:.0%}.",
                   "inputs": {"supplier_id": sid, "qty": qty, "arrival_day": lead}}
            evaluate(opt, extra=[(lead, qty)], stress_delay=int(round(perf["avg_delay_days"])) if perf else 3); cands.append(opt)
    elif "supplier_failure" in ctx["scenarios"]:
        excluded.append({"type": "EXPEDITE", "reason": "Not applicable: the incumbent supplier is offline, so there is nothing to expedite."})

    return score_and_recommend(d, pe, cands, excluded, budget, unmet)


_cache: dict[int, list] = {}


def evaluate_pairs_cached(d: Data, state: dict) -> list[dict]:
    key = id(state)
    if key not in _cache or _cache[key][0] is not state:
        _cache.clear(); _cache[key] = (state, evaluate_pairs(d, state))
    return _cache[key][1]


def score_and_recommend(d: Data, pe: dict, cands: list[dict], excluded: list[dict], budget: float | None, unmet: float) -> dict:
    base = cands[0]
    for o in cands:
        o["within_budget"] = budget is None or o["action_cost"] <= budget
        o.setdefault("reason", None)
        if o["feasible"] and not o["within_budget"]:
            o["reason"] = f"Action cost INR {o['action_cost']:,.0f} exceeds the budget limit INR {budget:,.0f}."
    pool = [o for o in cands if o["feasible"] and o["within_budget"]]
    def norm(key, o):
        vals = [(x.get(key) or 0.0) for x in pool]
        lo, hi = min(vals), max(vals)
        return 0.0 if hi - lo < 1e-9 else ((o.get(key) or 0.0) - lo) / (hi - lo)
    for o in cands:
        o["score"] = None
        if o in pool:
            pen = (SCORE_WEIGHTS["total_cost"] * norm("total_cost", o) + SCORE_WEIGHTS["recovery_days"] * norm("recovery_days", o)
                   + SCORE_WEIGHTS["production_loss"] * norm("production_loss_units", o) + SCORE_WEIGHTS["unmet_share"] * norm("unmet_share", o)
                   + SCORE_WEIGHTS["operational_risk"] * (o["operational_risk"] / 100.0))
            o["score"] = round(100 * (1 - pen), 1)
        if o["feasible"]:
            o["delta_total_cost"] = o["total_cost"] - base["total_cost"]
            o["delta_stockout_days"] = o["stockout_days"] - base["stockout_days"]
            o["delta_recovery_days"] = o["recovery_days"] - base["recovery_days"]
    interventions = [o for o in pool if o["type"] != "NO_ACTION"]
    rec, message = None, ""
    notes_unc = []
    if not interventions:
        message = ("No feasible intervention is available within the data and budget provided, so SupplyShield makes no confident recommendation. "
                   "See 'options not evaluated' for the reasons.")
    else:
        best = max(interventions, key=lambda o: (o["score"], -o["total_cost"]))
        if best["score"] <= base["score"]:
            rec = base
            message = "No intervention scores better than doing nothing under the current weights - staying with the baseline is the recommendation."
        else:
            rec = best
            message = (f"{best['label']} scores {best['score']} versus {base['score']} for no action. Estimated difference versus baseline: "
                       f"stockout {best['delta_stockout_days']:+.1f} days, recovery {best['delta_recovery_days']:+.0f} days, estimated total cost "
                       f"INR {best['delta_total_cost']:+,.0f} (action cost INR {best['action_cost']:,.0f} plus estimated production loss "
                       f"INR {(best['production_loss_cost'] or 0):,.0f}).")
            if best["stockout_days"] > 0.05:
                notes_unc.append(f"The option does not fully remove the shortage: about {best['stockout_days']:.1f} stockout days remain.")
            if best.get("stress_delay_days") and best["stress_stockout_days"] > best["stockout_days"] + 0.05:
                notes_unc.append(f"If the new supply arrives {best['stress_delay_days']} d late (that supplier's average historical delay), "
                                 f"stockout rises to {best['stress_stockout_days']:.1f} days.")
    if pe.get("missing_line_mapping"):
        notes_unc.append("No production line is mapped to this component, so production-loss cost is not estimated (shown as 0).")
    notes_unc += ["Disruption duration is a planning assumption, not a forecast.",
                  "Options are evaluated one at a time for this position; combinations and shared use of the same stock across positions are not modelled."]
    return {"factory_id": pe["factory_id"], "component_id": pe["component_id"], "options": cands, "excluded": excluded,
            "recommended_id": rec["option_id"] if rec else None, "message": message, "uncertainty": notes_unc,
            "shortfall_units": unmet}


# ------------------------------------------------------------------ top-level entry points
def run_scenario(d: Data, scenario: str, params: dict, budget: float | None = None) -> dict:
    p = validate_params(d, scenario, params)
    if budget is not None:
        try:
            budget = float(budget)
        except (TypeError, ValueError):
            raise ValidationError("budget must be a number.") from None
        if budget < 0:
            raise ValidationError("budget must not be negative.")
    state = base_state(d)
    apply_scenario(d, state, scenario, p)
    return summarise(d, state, scenario, p, budget)


def summarise(d: Data, state: dict, scenario: str, p: dict, budget: float | None) -> dict:
    _cache.clear()
    pairs = evaluate_pairs(d, state)
    _cache[id(state)] = (state, pairs)
    results, issues = [], []
    for pe in pairs:
        if not pe.get("assessable", True):
            if pe.get("reason"): issues.append({"factory_id": pe["factory_id"], "component_id": pe["component_id"], "reason": pe["reason"]})
            continue
        if not pe["affected"] and not pe["at_risk"]:
            continue
        item = {k: v for k, v in pe.items()}
        if pe["at_risk"]:
            item["recovery"] = build_options(d, state, pe, budget)
        results.append(item)
    at_risk = [r for r in results if r["at_risk"]]
    ch = [r for r in at_risk if r.get("production_loss_cost") is not None]
    return {"scenario": scenario, "params": p, "budget": budget, "as_of": d.as_of.isoformat(),
            "drivers": [{**x, "old_eta": _iso(d, x["old_eta"]), "new_eta": _iso(d, x["new_eta"])} for x in state["drivers"]],
            "pairs": results, "assessment_issues": issues,
            "summary": {"pairs_affected": len(results), "pairs_at_risk": len(at_risk),
                        "no_action_cost": sum(r["production_loss_cost"] or 0 for r in at_risk),
                        "max_recovery_days": max((r["disrupted"]["recovery_day"] for r in at_risk), default=0),
                        "earliest_stockout_days": min((r["disrupted"]["stockout_in_days"] for r in at_risk), default=None),
                        "cost_complete": len(ch) == len(at_risk)}}


def _iso(d: Data, off):
    from datetime import timedelta
    return None if off is None else (d.as_of + timedelta(days=off)).isoformat()
