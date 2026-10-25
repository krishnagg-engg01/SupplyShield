from datetime import date

from supplyshield import scenarios, synthetic

AS_OF = date(2026, 10, 16)


def raw():
    return synthetic.build_raw(AS_OF, seed=42)


def data(mutate=None):
    r = raw()
    if mutate:
        mutate(r)
    return scenarios.Data(synthetic.derive(r))


class FakeDB:
    """Stands in for ExasolService: answers the loader's queries from the synthetic dataset."""

    def __init__(self, fail=None):
        self.ds = synthetic.derive(raw()); self.fail = fail; self.inserted = []; self.executed = []

    def _chk(self):
        if self.fail:
            raise self.fail

    def health_check(self):
        self._chk(); return {"ok": True, "latency_ms": 1.0}

    def query(self, sql, params=None):
        self._chk()
        s = sql.upper()
        if "V_DASHBOARD_KPIS" in s: return [self.ds["kpi_counts"]]
        for view, key in (("V_INVENTORY_POSITION", "inventory"), ("V_SUPPLIER_PERFORMANCE", "supplier_performance"), ("V_SUPPLIER_COMMITMENT", "supplier_commitment")):
            if view in s: return self.ds[key]
        for t in ("DATASET_META", "COMPONENTS", "SUPPLIER_COMPONENTS", "SUPPLIERS", "FACTORIES", "PRODUCTION_LINES", "ROUTES", "SHIPMENTS", "DELIVERY_HISTORY", "DISRUPTIONS"):
            if f"FROM {t}" in s: return self.ds[t.lower()]
        if "FROM SCENARIO_RUNS" in s: return []
        if "COUNT(*)" in s: return [{"n": 1}]
        raise AssertionError("unexpected SQL: " + sql)

    def table_counts(self):
        return {"components": 6}

    def insert_rows(self, table, columns, rows, **kw):
        self._chk(); self.inserted.append((table, list(columns), rows)); return len(rows)

    def execute(self, sql, params=None):
        self._chk(); self.executed.append((sql, params))
