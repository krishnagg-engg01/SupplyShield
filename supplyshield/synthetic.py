"""Reproducible SYNTHETIC dataset telling one story:

    Shenzhen MicroSemi (S-SZX), the sole current source of motor-control MCUs for Chennai and Pune,
    suffers a fab fire -> scheduled MCU shipments stop -> Chennai and Pune run out of MCUs while the
    Ahmedabad plant holds spare stock -> SupplyShield compares recovery options.

Everything is invented for demonstration; no real company data is used.
"""
from __future__ import annotations

import random
from datetime import date, datetime, timedelta, timezone

from . import analytics
from .config import SEED_TABLE_ORDER, TABLE_COLUMNS

DEFAULT_SEED = 42


def _d(as_of: date, offset: int) -> date:
    return as_of + timedelta(days=offset)


def build_raw(as_of: date | None = None, seed: int = DEFAULT_SEED) -> dict:
    as_of = as_of or date.today()
    rng = random.Random(seed)
    components = [
        ("C-MCU", "Motor-control MCU", 5, 400.0, "pcs"), ("C-BAT", "Li-ion cell pack", 5, 1800.0, "pcs"),
        ("C-PCB", "Driver PCB assembly", 4, 260.0, "pcs"), ("C-HSG", "Aluminium housing", 3, 310.0, "pcs"),
        ("C-SNS", "Hall-effect sensor", 3, 95.0, "pcs"), ("C-HRN", "Wiring harness", 2, 140.0, "pcs"),
    ]
    suppliers = [
        ("S-SZX", "Shenzhen MicroSemi", "Shenzhen", "China", "EAST_ASIA", "ACTIVE"),
        ("S-TPE", "Taipei ChipWorks", "Hsinchu", "Taiwan", "EAST_ASIA", "ACTIVE"),
        ("S-BLR", "Bengaluru Embedded Systems", "Bengaluru", "India", "INDIA", "ACTIVE"),
        ("S-PUN", "Pune PCB Works", "Pune", "India", "INDIA", "ACTIVE"),
        ("S-HAN", "Hanoi CellTech", "Hanoi", "Vietnam", "SE_ASIA", "ACTIVE"),
        ("S-GUJ", "Gujarat Energy Cells", "Sanand", "India", "INDIA", "ACTIVE"),
        ("S-CBE", "Coimbatore Castings & Wiring", "Coimbatore", "India", "INDIA", "ACTIVE"),
        ("S-PEN", "Penang Sensor Tech", "Penang", "Malaysia", "SE_ASIA", "ACTIVE"),
    ]
    supplier_components = [
        ("S-SZX", "C-MCU", 400.0, 12, 900), ("S-TPE", "C-MCU", 455.0, 14, 400), ("S-BLR", "C-MCU", 520.0, 6, 120),
        ("S-BLR", "C-SNS", 118.0, 7, 600), ("S-PUN", "C-PCB", 255.0, 5, 800), ("S-HAN", "C-BAT", 1780.0, 10, 300),
        ("S-GUJ", "C-BAT", 1960.0, 7, 150), ("S-CBE", "C-HSG", 305.0, 4, 500), ("S-CBE", "C-HRN", 138.0, 4, 900),
        ("S-PEN", "C-SNS", 92.0, 12, 1200),
    ]
    factories = [("F-CHN", "Chennai Plant", "Sriperumbudur"), ("F-PUN", "Pune Plant", "Chakan"), ("F-AMD", "Ahmedabad Plant", "Sanand")]
    lines = [
        ("L-CHN-1", "F-CHN", "Drive Unit Line A", "C-MCU", 260, 1, 1150.0),
        ("L-CHN-2", "F-CHN", "Battery Pack Line", "C-BAT", 150, 1, 2400.0),
        ("L-CHN-3", "F-CHN", "Harness Sub-assembly", "C-HRN", 400, 1, 180.0),
        ("L-PUN-1", "F-PUN", "Drive Unit Line B", "C-MCU", 180, 1, 1150.0),
        ("L-PUN-2", "F-PUN", "Controller PCB Line", "C-PCB", 320, 1, 420.0),
        ("L-AMD-1", "F-AMD", "Smart Controller Line", "C-MCU", 60, 1, 1600.0),
        ("L-AMD-2", "F-AMD", "Housing Assembly", "C-HSG", 220, 1, 260.0),
        ("L-AMD-3", "F-AMD", "Sensor Module Line", "C-SNS", 150, 2, 340.0),
    ]
    routes = [
        ("R-01", "East Asia - Chennai, sea via Chennai Port", "EAST_ASIA", "F-CHN", "Chennai Port", "SEA", 16, 6.0, "OPEN"),
        ("R-02", "East Asia - Chennai, sea via Krishnapatnam + road", "EAST_ASIA", "F-CHN", "Krishnapatnam Port", "SEA", 20, 9.0, "OPEN"),
        ("R-03", "East Asia - Chennai, air", "EAST_ASIA", "F-CHN", "Chennai Airport", "AIR", 5, 70.0, "OPEN"),
        ("R-04", "East Asia - Pune, sea via Nhava Sheva", "EAST_ASIA", "F-PUN", "Nhava Sheva Port", "SEA", 18, 7.0, "OPEN"),
        ("R-05", "East Asia - Pune, air", "EAST_ASIA", "F-PUN", "Pune Airport", "AIR", 6, 75.0, "OPEN"),
        ("R-06", "East Asia - Ahmedabad, sea via Mundra", "EAST_ASIA", "F-AMD", "Mundra Port", "SEA", 17, 7.0, "OPEN"),
        ("R-07", "East Asia - Ahmedabad, air", "EAST_ASIA", "F-AMD", "Ahmedabad Airport", "AIR", 5, 72.0, "OPEN"),
        ("R-20", "SE Asia - Chennai, sea via Chennai Port", "SE_ASIA", "F-CHN", "Chennai Port", "SEA", 10, 5.0, "OPEN"),
        ("R-21", "SE Asia - Chennai, air", "SE_ASIA", "F-CHN", "Chennai Airport", "AIR", 4, 60.0, "OPEN"),
        ("R-22", "SE Asia - Ahmedabad, sea via Mundra", "SE_ASIA", "F-AMD", "Mundra Port", "SEA", 14, 5.0, "OPEN"),
        ("R-23", "SE Asia - Ahmedabad, air", "SE_ASIA", "F-AMD", "Ahmedabad Airport", "AIR", 4, 58.0, "OPEN"),
        ("R-30", "India - Chennai, road", "INDIA", "F-CHN", None, "ROAD", 3, 2.0, "OPEN"),
        ("R-31", "India - Pune, road", "INDIA", "F-PUN", None, "ROAD", 2, 2.0, "OPEN"),
        ("R-32", "India - Ahmedabad, road", "INDIA", "F-AMD", None, "ROAD", 3, 2.5, "OPEN"),
    ]
    # on_hand, safety, reorder, daily consumption (= line output x qty_per_unit)
    inventory = [
        ("F-CHN", "C-MCU", 4800, 780, 1560, 260), ("F-CHN", "C-BAT", 2100, 450, 900, 150), ("F-CHN", "C-HRN", 5200, 800, 2000, 400),
        ("F-PUN", "C-MCU", 3600, 540, 1080, 180), ("F-PUN", "C-PCB", 4800, 960, 1920, 320),
        ("F-AMD", "C-MCU", 2600, 360, 600, 60), ("F-AMD", "C-HSG", 1400, 660, 1500, 220), ("F-AMD", "C-SNS", 6200, 1200, 2400, 300),
    ]
    sh = [  # id, supplier, factory, component, route, qty, planned offset, est offset, status
        ("SH-1001", "S-SZX", "F-CHN", "C-MCU", "R-01", 6000, 16, 16, "SCHEDULED"),
        ("SH-1002", "S-SZX", "F-PUN", "C-MCU", "R-04", 5000, 18, 18, "SCHEDULED"),
        ("SH-1003", "S-SZX", "F-CHN", "C-MCU", "R-01", 3000, 30, 30, "SCHEDULED"),
        ("SH-1004", "S-HAN", "F-CHN", "C-BAT", "R-20", 2000, 6, 6, "IN_TRANSIT"),
        ("SH-1005", "S-CBE", "F-AMD", "C-HSG", "R-32", 2500, 5, 6, "DELAYED"),
        ("SH-1006", "S-PEN", "F-AMD", "C-SNS", "R-22", 5000, 8, 10, "DELAYED"),
        ("SH-1007", "S-PUN", "F-PUN", "C-PCB", "R-31", 4000, 7, 7, "IN_TRANSIT"),
        ("SH-1008", "S-CBE", "F-CHN", "C-HRN", "R-30", 6000, 8, 8, "SCHEDULED"),
        ("SH-1009", "S-BLR", "F-AMD", "C-MCU", "R-32", 1500, 10, 10, "SCHEDULED"),
        ("SH-1010", "S-HAN", "F-CHN", "C-BAT", "R-20", 1800, -3, -3, "DELIVERED"),
        ("SH-1011", "S-HAN", "F-CHN", "C-BAT", "R-20", 3000, 26, 26, "SCHEDULED"),
        ("SH-1012", "S-CBE", "F-CHN", "C-HRN", "R-30", 7000, 24, 24, "SCHEDULED"),
        ("SH-1013", "S-PUN", "F-PUN", "C-PCB", "R-31", 6000, 24, 24, "SCHEDULED"),
        ("SH-1014", "S-CBE", "F-AMD", "C-HSG", "R-32", 7000, 16, 16, "SCHEDULED"),
        ("SH-1015", "S-PEN", "F-AMD", "C-SNS", "R-22", 4000, 30, 30, "SCHEDULED"),
    ]
    shipments = [(i, s, f, c, r, q, _d(as_of, p), _d(as_of, e), st) for i, s, f, c, r, q, p, e, st in sh]
    # delivery history: 12 deliveries per supplier-component, exact on-time share per supplier
    on_time_target = {"S-SZX": 10 / 12, "S-TPE": 11 / 12, "S-BLR": 12 / 12, "S-PUN": 11 / 12,
                      "S-HAN": 9 / 12, "S-GUJ": 10 / 12, "S-CBE": 11 / 12, "S-PEN": 8 / 12}
    history, n = [], 0
    for sid, cid, *_ in supplier_components:
        k_on = round(on_time_target[sid] * 12)
        flags = [True] * k_on + [False] * (12 - k_on)
        rng.shuffle(flags)
        for j, ok in enumerate(flags):
            n += 1
            promised = _d(as_of, -170 + j * 14 + rng.randint(0, 3))
            actual = promised - timedelta(days=rng.randint(0, 1)) if ok else promised + timedelta(days=rng.randint(1, 6))
            history.append((f"DL-{n:04d}", sid, cid, promised, actual, rng.choice([800, 1000, 1500, 2000, 3000])))
    disruptions = [
        ("D-001", "SUPPLIER_FAILURE", "SUPPLIER", "S-SZX", _d(as_of, -1), 21, "CRITICAL", "OPEN",
         "SYNTHETIC EVENT: fab fire at Shenzhen MicroSemi; undispatched shipments are halted. Restart not confirmed - 21 days is a planning assumption."),
        ("D-002", "SHIPMENT_DELAY", "SHIPMENT", "SH-1006", _d(as_of, -2), 2, "LOW", "OPEN",
         "SYNTHETIC EVENT: customs hold at Mundra; ETA already moved by 2 days in the shipment record."),
        ("D-000", "PORT_CLOSURE", "PORT", "Nhava Sheva Port", _d(as_of, -40), 4, "MEDIUM", "RESOLVED",
         "SYNTHETIC EVENT: weather closure, resolved (history only)."),
    ]
    meta = [("label", "SYNTHETIC"), ("seed", str(seed)), ("as_of", as_of.isoformat()),
            ("generated_at", datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")),
            ("note", "Invented demonstration data. Not real company data.")]
    tables = {"dataset_meta": meta, "components": components, "suppliers": suppliers, "supplier_components": supplier_components,
              "factories": factories, "production_lines": lines, "routes": routes, "inventory": inventory,
              "shipments": shipments, "delivery_history": history, "disruptions": disruptions}
    return {t: [dict(zip(TABLE_COLUMNS[t], row)) for row in tables[t]] for t in SEED_TABLE_ORDER}


def table_rows(raw: dict, table: str) -> list[tuple]:
    """Rows as tuples in TABLE_COLUMNS order (for the seed script)."""
    return [tuple(r[c] for c in TABLE_COLUMNS[table]) for r in raw[table]]


def check_integrity(raw: dict) -> list[str]:
    """Return referential/consistency problems (empty list = consistent). Exasol does not enforce FKs."""
    errs = []
    ids = {t: {r[TABLE_COLUMNS[t][0]] for r in raw[t]} for t in ("components", "suppliers", "factories", "routes", "shipments")}
    def need(table, col, target):
        for r in raw[table]:
            if r[col] is not None and r[col] not in ids[target]:
                errs.append(f"{table}.{col}={r[col]} not in {target}")
    for col, tgt in (("supplier_id", "suppliers"), ("component_id", "components")):
        need("supplier_components", col, tgt); need("delivery_history", col, tgt); need("shipments", col, tgt)
    need("shipments", "factory_id", "factories"); need("shipments", "route_id", "routes")
    need("production_lines", "factory_id", "factories"); need("production_lines", "component_id", "components")
    need("inventory", "factory_id", "factories"); need("inventory", "component_id", "components")
    need("routes", "destination_factory_id", "factories")
    inv = {(r["factory_id"], r["component_id"]): r for r in raw["inventory"]}
    for ln in raw["production_lines"]:
        key = (ln["factory_id"], ln["component_id"])
        if key not in inv:
            errs.append(f"line {ln['line_id']} has no inventory row {key}")
    for key, r in inv.items():
        expected = sum(l["daily_output_units"] * l["qty_per_unit"] for l in raw["production_lines"] if (l["factory_id"], l["component_id"]) == key)
        if expected and abs(expected - r["daily_consumption"]) > 1e-6:
            errs.append(f"inventory {key} consumption {r['daily_consumption']} != lines {expected}")
    routes = {r["route_id"]: r for r in raw["routes"]}
    sup = {r["supplier_id"]: r for r in raw["suppliers"]}
    for s in raw["shipments"]:
        r = routes.get(s["route_id"])
        if r and (r["destination_factory_id"] != s["factory_id"] or r["origin_region"] != sup.get(s["supplier_id"], {}).get("region")):
            errs.append(f"shipment {s['shipment_id']} route does not match supplier region / factory")
    return errs


def derive(raw: dict) -> dict:
    """Add the aggregates that Exasol's views provide, computed in Python (demo mode)."""
    comps = {c["component_id"]: c for c in raw["components"]}
    data = dict(raw)
    data["inventory"] = analytics.inventory_position(raw["inventory"], comps)
    data["supplier_performance"] = analytics.supplier_performance_from_history(raw["delivery_history"])
    data["supplier_commitment"] = analytics.commitment_from_shipments(raw["shipments"])
    data["kpi_counts"] = analytics.kpi_counts(raw)
    return data
