import re
import unittest

from supplyshield.config import SQL_DIR, TABLE_COLUMNS, ExasolSettings, get_settings, validate_identifier
from supplyshield.db import ExasolError, ExasolService, split_statements

GOOD = ExasolSettings(dsn="db.example:8563", user="u", password="s3cret-pw", schema="SUPPLYSHIELD")


class FakeStmt:
    def __init__(self, rows): self.rows = rows
    def fetchall(self): return self.rows


class FakeConn:
    def __init__(self, rows=None, fail_on=None):
        self.calls, self.rows, self.fail_on, self.closed = [], rows or [{"OK": 1}], fail_on, False
    def execute(self, sql, params=None):
        self.calls.append((sql, params))
        if self.fail_on and self.fail_on in sql: raise RuntimeError("boom s3cret-pw")
        return FakeStmt(self.rows)
    def close(self): self.closed = True


class Settings(unittest.TestCase):
    def test_missing_reported(self):
        s = get_settings({}); self.assertEqual(s.missing(), ["EXASOL_DSN", "EXASOL_USER", "EXASOL_PASSWORD"]); self.assertFalse(s.configured)

    def test_public_view_never_contains_password(self):
        self.assertNotIn("s3cret-pw", str(GOOD.public())); self.assertTrue(GOOD.public()["password_set"])

    def test_schema_is_validated(self):
        with self.assertRaises(ValueError): get_settings({"EXASOL_SCHEMA": "x; DROP SCHEMA y"})

    def test_identifier_validation(self):
        for bad in ("a b", "1abc", "t;--", "", 'x"y', None): 
            with self.assertRaises(ValueError): validate_identifier(bad)
        self.assertEqual(validate_identifier("SHIPMENTS"), "SHIPMENTS")


class Connection(unittest.TestCase):
    def test_health_check_runs_a_real_select_1(self):
        c = FakeConn(); res = ExasolService(GOOD, connect_fn=lambda **k: c).health_check()
        self.assertTrue(res["ok"]); self.assertEqual(c.calls[0][0], "SELECT 1 AS ok"); self.assertTrue(c.closed)

    def test_health_check_fails_if_query_does_not_return_one(self):
        with self.assertRaises(ExasolError): ExasolService(GOOD, connect_fn=lambda **k: FakeConn(rows=[{"OK": 0}])).health_check()

    def test_not_configured(self):
        with self.assertRaises(ExasolError) as cm: ExasolService(ExasolSettings()).health_check()
        self.assertEqual(cm.exception.kind, "not_configured")

    def test_network_failure_is_friendly(self):
        def boom(**k): raise OSError("[Errno 111] Connection refused")
        with self.assertRaises(ExasolError) as cm: ExasolService(GOOD, connect_fn=boom).health_check()
        self.assertEqual(cm.exception.kind, "network"); self.assertIn("EXASOL_DSN", cm.exception.message)

    def test_auth_failure_is_friendly(self):
        class ExaAuthError(Exception): pass
        def boom(**k): raise ExaAuthError("bad credentials")
        with self.assertRaises(ExasolError) as cm: ExasolService(GOOD, connect_fn=boom).health_check()
        self.assertEqual(cm.exception.kind, "auth")

    def test_password_never_leaks_into_errors(self):
        with self.assertRaises(ExasolError) as cm: ExasolService(GOOD, connect_fn=lambda **k: FakeConn(fail_on="SELECT 1")).health_check()
        self.assertNotIn("s3cret-pw", cm.exception.message)
        def boom(**k): raise RuntimeError("could not connect with password s3cret-pw")
        with self.assertRaises(ExasolError) as cm: ExasolService(GOOD, connect_fn=boom).health_check()
        self.assertNotIn("s3cret-pw", cm.exception.message)

    def test_self_signed_cert_option_only_when_requested(self):
        seen = {}
        def capture(**k): seen.update(k); return FakeConn()
        ExasolService(GOOD, connect_fn=capture).health_check(); self.assertNotIn("websocket_sslopt", seen)
        relaxed = ExasolSettings(dsn="h:1", user="u", password="p", validate_cert=False)
        ExasolService(relaxed, connect_fn=capture).health_check(); self.assertIn("websocket_sslopt", seen)

    def test_query_lowercases_keys_and_converts_decimals(self):
        from decimal import Decimal
        c = FakeConn(rows=[{"FACTORY_ID": "F1", "QTY": Decimal("2.5")}])
        rows = ExasolService(GOOD, connect_fn=lambda **k: c).query("SELECT * FROM X WHERE a = {a}", {"a": 1})
        self.assertEqual(rows, [{"factory_id": "F1", "qty": 2.5}]); self.assertEqual(c.calls[-1][1], {"a": 1})

    def test_query_error_closes_connection(self):
        c = FakeConn(fail_on="SELECT BAD")
        with self.assertRaises(ExasolError): ExasolService(GOOD, connect_fn=lambda **k: c).query("SELECT BAD")
        self.assertTrue(c.closed)


class Inserts(unittest.TestCase):
    def svc(self, c): return ExasolService(GOOD, connect_fn=lambda **k: c)

    def test_insert_is_parameterised_and_identifier_quoted(self):
        c = FakeConn(); self.svc(c).insert_rows("components", ["component_id", "name"], [("C1", "x'; DROP TABLE y;--")])
        sql, params = c.calls[-1]
        self.assertIn("INSERT INTO {t!i}", sql); self.assertNotIn("DROP", sql); self.assertIn("x'; DROP", params["p0_1"])

    def test_rejects_unlisted_table_and_column(self):
        c = FakeConn()
        with self.assertRaises(ValueError): self.svc(c).insert_rows("users", ["a"], [(1,)])
        with self.assertRaises(ValueError): self.svc(c).insert_rows("components", ["component_id; DROP"], [(1,)])
        with self.assertRaises(ValueError): self.svc(c).insert_rows("components", ["secret_col"], [(1,)])

    def test_row_length_checked(self):
        with self.assertRaises(ValueError): self.svc(FakeConn()).insert_rows("components", ["component_id", "name"], [("only-one",)])

    def test_chunking(self):
        c = FakeConn(); self.svc(c).insert_rows("factories", ["factory_id", "name", "location"], [(f"F{i}", "n", "l") for i in range(250)], chunk=100)
        self.assertEqual(len([x for x in c.calls if x[0].startswith("INSERT")]), 3)


class SqlFiles(unittest.TestCase):
    schema = (SQL_DIR / "01_schema.sql").read_text()

    def test_every_allow_listed_table_exists_with_matching_columns(self):
        for table, cols in TABLE_COLUMNS.items():
            m = re.search(rf"CREATE TABLE {table}\s*\((.*?)\n\);", self.schema, re.S | re.I)
            self.assertIsNotNone(m, table)
            found = [ln.split()[0].lower() for ln in m.group(1).splitlines() if ln.strip() and not ln.strip().startswith(("--", "CONSTRAINT"))]
            self.assertEqual(found, list(cols), table)

    def test_statements_split_cleanly(self):
        stmts = split_statements(self.schema); self.assertEqual(len(stmts), len(TABLE_COLUMNS)); self.assertTrue(all(s.startswith("CREATE TABLE") for s in stmts))

    def test_views_defined(self):
        views = (SQL_DIR / "02_views.sql").read_text().upper()
        for v in ("V_INVENTORY_POSITION", "V_SUPPLIER_PERFORMANCE", "V_SUPPLIER_COMMITMENT", "V_INBOUND_SUPPLY", "V_DISRUPTION_IMPACT", "V_ALT_SUPPLIER_CANDIDATES", "V_DASHBOARD_KPIS", "V_RECOVERY_COMPARISON"):
            self.assertIn(f"CREATE OR REPLACE VIEW {v}", views)

    def test_no_credentials_in_repo_sql(self):
        for f in SQL_DIR.glob("*.sql"): self.assertNotRegex(f.read_text().lower(), r"password\s*=|identified by")


if __name__ == "__main__":
    unittest.main()
