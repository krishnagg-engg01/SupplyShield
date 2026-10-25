"""Deterministic, explainable baseline calculations (pure functions, no I/O).

Units: quantities in component units, time in days, money in INR.
"""
from __future__ import annotations

import math
from datetime import date
from typing import Iterable

from .config import ASSUMPTIONS, SUPPLIER_RISK_WEIGHTS


class ValidationError(ValueError):
    """Invalid user input or inconsistent data. `errors` lists readable messages."""

    def __init__(self, errors: list[str] | str):
        self.errors = [errors] if isinstance(errors, str) else list(errors)
        super().__init__("; ".join(self.errors))


def _num(value, name: str, allow_none: bool = False):
    if value is None:
        if allow_none:
            return None
        raise ValidationError(f"{name} is missing.")
    try:
        v = float(value)
    except (TypeError, ValueError):
        raise ValidationError(f"{name} must be a number, got {value!r}.") from None
    if math.isnan(v) or math.isinf(v):
        raise ValidationError(f"{name} must be a finite number.")
    return v


def usable_stock(on_hand) -> float | None:
    """Usable stock = on-hand quantity, with negative (data error) values floored at zero."""
    v = _num(on_hand, "on_hand", allow_none=True)
    return None if v is None else max(v, 0.0)


def cover_days(on_hand, daily_consumption) -> float | None:
    """Inventory cover days = usable stock / daily consumption; None if consumption is not positive/known."""
    stock = usable_stock(on_hand)
    daily = _num(daily_consumption, "daily_consumption", allow_none=True)
    if stock is None or daily is None or daily <= 0:
        return None
    return stock / daily


def simulate_inventory(on_hand, daily_consumption, arrivals: Iterable[tuple[int, float]],
                       horizon: int | None = None, demand_surge: tuple[float, int] | None = None) -> dict:
    """Day-by-day stock projection.

    arrivals: (day_offset, qty). Qty arriving on day d is usable on day d. Past arrivals (<0) count on day 0.
    demand_surge: (multiplier, days) applied to the first `days` days.
    Returns first stockout (fractional days from today), equivalent stockout days, unmet units, the
    recovery day (first day after the last short day) and the stock series (end of each day).
    """
    horizon = int(horizon or ASSUMPTIONS["horizon_days"])
    stock = usable_stock(on_hand)
    daily = _num(daily_consumption, "daily_consumption")
    if stock is None:
        raise ValidationError("on_hand is missing.")
    if daily < 0:
        raise ValidationError("daily_consumption must not be negative.")
    by_day: dict[int, float] = {}
    for day, qty in arrivals:
        q = _num(qty, "arrival quantity")
        if q < 0:
            raise ValidationError("Arrival quantities must not be negative.")
        d = max(int(day), 0)
        if d < horizon:
            by_day[d] = by_day.get(d, 0.0) + q
    series, first_stockout, unmet, demand_total, last_short = [], None, 0.0, 0.0, None
    for d in range(horizon):
        stock += by_day.get(d, 0.0)
        mult, surge_days = demand_surge if demand_surge else (1.0, 0)
        demand = daily * (mult if d < surge_days else 1.0)
        demand_total += demand
        if stock >= demand:
            stock -= demand
        else:
            if first_stockout is None and demand > 0:
                first_stockout = d + stock / demand
            unmet += demand - stock
            stock = 0.0
            last_short = d
        series.append(round(stock, 2))
    recovered = last_short is None or last_short < horizon - 1
    recovery_day = 0 if last_short is None else (last_short + 1 if recovered else horizon)
    stockout_days = (unmet / daily) if daily > 0 else 0.0
    return {"stockout_in_days": first_stockout, "stockout_days": stockout_days, "unmet_units": unmet,
            "unmet_share": (unmet / demand_total) if demand_total > 0 else 0.0,
            "recovery_day": recovery_day, "recovered": recovered, "series": series, "demand_total": demand_total}


def supplier_risk_score(on_time_rate=None, avg_delay_days=None, lead_time_days=None,
                        capacity_utilisation=None, criticality=None) -> dict:
    """0-100 risk score (higher = riskier) from available factors; missing factors are skipped and the
    remaining weights are re-normalised. With under half the weight available, no score is produced.

    factor risk (0..1): on_time = 1 - rate; delay = avg_delay/10 (cap 1); lead_time = lead/45 (cap 1);
    capacity = utilisation of capacity by committed volume (cap 1); criticality = (crit-1)/4.
    """
    raw = {
        "on_time": None if on_time_rate is None else 1 - min(max(float(on_time_rate), 0), 1),
        "delay": None if avg_delay_days is None else min(max(float(avg_delay_days), 0) / 10, 1),
        "lead_time": None if lead_time_days is None else min(max(float(lead_time_days), 0) / 45, 1),
        "capacity": None if capacity_utilisation is None else min(max(float(capacity_utilisation), 0), 1),
        "criticality": None if criticality is None else min(max((float(criticality) - 1) / 4, 0), 1),
    }
    avail = {k: v for k, v in raw.items() if v is not None}
    missing = [k for k in raw if raw[k] is None]
    total_w = sum(SUPPLIER_RISK_WEIGHTS.values())
    avail_w = sum(SUPPLIER_RISK_WEIGHTS[k] for k in avail)
    coverage = avail_w / total_w
    factors = [{"factor": k, "risk": round(v, 3), "weight": SUPPLIER_RISK_WEIGHTS[k]} for k, v in avail.items()]
    if coverage < 0.5:
        return {"score": None, "band": "UNKNOWN", "coverage": round(coverage, 2), "missing": missing, "factors": factors}
    score = 100 * sum(v * SUPPLIER_RISK_WEIGHTS[k] for k, v in avail.items()) / avail_w
    band = "LOW" if score < 25 else "MODERATE" if score < 45 else "HIGH" if score < 65 else "CRITICAL"
    return {"score": round(score, 1), "band": band, "coverage": round(coverage, 2), "missing": missing, "factors": factors}


# ---- Python equivalents of the SQL views (used for demo mode, and to cross-check Exasol) ----
def supplier_performance_from_history(history: list[dict]) -> list[dict]:
    acc: dict[str, list[dict]] = {}
    for h in history:
        acc.setdefault(h["supplier_id"], []).append(h)
    out = []
    for sid, rows in sorted(acc.items()):
        n = len(rows)
        on_time = sum(1 for r in rows if r["actual_date"] <= r["promised_date"])
        delays = [max((r["actual_date"] - r["promised_date"]).days, 0) for r in rows]
        out.append({"supplier_id": sid, "n_deliveries": n, "on_time_rate": round(on_time / n, 4),
                    "avg_delay_days": round(sum(delays) / n, 2)})
    return out


def commitment_from_shipments(shipments: list[dict]) -> list[dict]:
    acc: dict[str, dict] = {}
    for s in shipments:
        if s["status"] in ASSUMPTIONS["inbound_statuses"]:
            a = acc.setdefault(s["supplier_id"], {"supplier_id": s["supplier_id"], "open_shipments": 0, "open_qty": 0.0})
            a["open_shipments"] += 1
            a["open_qty"] += float(s["quantity"])
    return sorted(acc.values(), key=lambda r: r["supplier_id"])


def inventory_position(inv: list[dict], components: dict[str, dict]) -> list[dict]:
    out = []
    for r in inv:
        us = usable_stock(r["on_hand_qty"])
        out.append({**r, "component_name": components[r["component_id"]]["name"],
                    "criticality": components[r["component_id"]]["criticality"], "usable_stock": us,
                    "cover_days": None if r["daily_consumption"] is None or float(r["daily_consumption"]) <= 0
                    else round(us / float(r["daily_consumption"]), 2),
                    "below_reorder": 1 if float(r["on_hand_qty"]) <= float(r["reorder_point_qty"]) else 0})
    return out


def kpi_counts(raw: dict) -> dict:
    inbound = [s for s in raw["shipments"] if s["status"] in ASSUMPTIONS["inbound_statuses"]]
    return {"open_disruptions": sum(1 for d in raw["disruptions"] if d["status"] == "OPEN"),
            "below_reorder_positions": sum(1 for r in raw["inventory"] if float(r["on_hand_qty"]) <= float(r["reorder_point_qty"])),
            "delayed_shipments": sum(1 for s in inbound if s["estimated_arrival"] > s["planned_arrival"]),
            "inbound_qty": sum(float(s["quantity"]) for s in inbound)}


def day_offset(d: date, as_of: date) -> int:
    return (d - as_of).days
