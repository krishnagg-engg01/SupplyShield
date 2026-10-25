"""Exasol data-access layer (PyExasol).

* Every call opens a short-lived websocket connection and closes it again.
* Values are passed through PyExasol's query formatter (`{name}` placeholders),
  identifiers through `{name!i}`. Dynamic table / column names are validated
  against an allow-list (see config.TABLE_COLUMNS).
* Errors are converted to ExasolError with a friendly, secret-free message.
"""
from __future__ import annotations

import re
import ssl
import time
from decimal import Decimal
from typing import Any, Callable, Iterable

from .config import TABLE_COLUMNS, ExasolSettings, validate_identifier


class ExasolError(Exception):
    """A connection or query problem. `kind` helps the UI pick a hint."""

    def __init__(self, message: str, kind: str = "query"):
        super().__init__(message)
        self.message = message
        self.kind = kind


def _clean(value: Any):
    if isinstance(value, Decimal):
        return float(value)
    return value


def split_statements(script: str) -> list[str]:
    """Split a SQL script on semicolons (our scripts contain none inside strings)."""
    text = re.sub(r"--[^\n]*", "", script)  # strip comments (our scripts have no '--' inside strings)
    return [s.strip() for s in text.split(";") if s.strip()]


class ExasolService:
    def __init__(self, settings: ExasolSettings, connect_fn: Callable[..., Any] | None = None):
        self.settings = settings
        self._connect_fn = connect_fn  # injectable for tests

    # ---- connection -------------------------------------------------
    def _sanitize(self, text: str) -> str:
        pw = self.settings.password
        return text.replace(pw, "***") if pw else text

    def _connect(self, open_schema: bool = True):
        s = self.settings
        if not s.configured:
            raise ExasolError("Missing connection settings: " + ", ".join(s.missing()), "not_configured")
        if self._connect_fn is None:
            try:
                import pyexasol
            except ImportError as exc:
                raise ExasolError("The 'pyexasol' package is not installed. Run: pip install -r requirements.txt", "setup") from exc
            connect = pyexasol.connect
        else:
            connect = self._connect_fn
        kwargs: dict[str, Any] = dict(dsn=s.dsn, user=s.user, password=s.password, encryption=s.encryption,
                                      fetch_dict=True, compression=False, connection_timeout=10)
        if s.encryption and not s.validate_cert:
            kwargs["websocket_sslopt"] = {"cert_reqs": ssl.CERT_NONE}
        try:
            conn = connect(**kwargs)
        except Exception as exc:  # noqa: BLE001 - classified below
            raise self._classify(exc) from None
        if open_schema:
            try:
                conn.execute("OPEN SCHEMA {schema!i}", {"schema": s.schema})
            except Exception as exc:  # noqa: BLE001
                self._close(conn)
                raise ExasolError(f"Connected, but schema {s.schema} could not be opened. "
                                  "Run 'python scripts/init_db.py' and 'python scripts/seed_db.py' first.", "schema") from exc
        return conn

    @staticmethod
    def _close(conn) -> None:
        try:
            conn.close()
        except Exception:  # noqa: BLE001
            pass

    def _classify(self, exc: Exception) -> ExasolError:
        name = type(exc).__name__
        raw = self._sanitize(str(exc))[:300]
        low = raw.lower()
        if "auth" in name.lower() or "password" in low or "authentication" in low:
            return ExasolError("Authentication failed. Check EXASOL_USER and EXASOL_PASSWORD.", "auth")
        if isinstance(exc, ssl.SSLError) or "certificate" in low or "ssl" in low:
            return ExasolError("TLS certificate could not be verified. For a self-signed certificate set EXASOL_VALIDATE_CERT=false "
                               "(development only) or put the certificate fingerprint in EXASOL_DSN.", "tls")
        if isinstance(exc, (OSError, TimeoutError)) or "connection" in name.lower() or "timed out" in low or "refused" in low:
            return ExasolError(f"Could not reach Exasol at the configured DSN ({raw or name}). Check EXASOL_DSN, that the instance is running and reachable.", "network")
        return ExasolError(f"{name}: {raw}", "query")

    # ---- public API -------------------------------------------------
    def health_check(self) -> dict:
        """Run a real SELECT 1. Never reports success unless the query returned."""
        t0 = time.perf_counter()
        conn = self._connect(open_schema=False)
        try:
            rows = conn.execute("SELECT 1 AS ok").fetchall()
        except Exception as exc:  # noqa: BLE001
            raise self._classify(exc) from None
        finally:
            self._close(conn)
        first = rows[0] if rows else None
        value = (list(first.values())[0] if isinstance(first, dict) else (first[0] if first else None))
        if value is None or int(_clean(value)) != 1:
            raise ExasolError("Health check query did not return 1.", "query")
        return {"ok": True, "latency_ms": round((time.perf_counter() - t0) * 1000, 1)}

    def query(self, sql: str, params: dict | None = None) -> list[dict]:
        conn = self._connect()
        try:
            rows = conn.execute(sql, params or {}).fetchall()
        except Exception as exc:  # noqa: BLE001
            raise self._classify(exc) from None
        finally:
            self._close(conn)
        return [{str(k).lower(): _clean(v) for k, v in r.items()} for r in rows]

    def execute(self, sql: str, params: dict | None = None) -> None:
        conn = self._connect()
        try:
            conn.execute(sql, params or {})
        except Exception as exc:  # noqa: BLE001
            raise self._classify(exc) from None
        finally:
            self._close(conn)

    def insert_rows(self, table: str, columns: Iterable[str], rows: list[tuple], chunk: int = 100,
                    conn=None) -> int:
        """Bulk insert with allow-listed identifiers and formatted (escaped) values."""
        table = validate_identifier(table, "table").lower()
        if table not in TABLE_COLUMNS:
            raise ValueError(f"Table {table!r} is not allow-listed.")
        columns = [validate_identifier(c, "column").lower() for c in columns]
        unknown = set(columns) - set(TABLE_COLUMNS[table])
        if unknown:
            raise ValueError(f"Columns not allowed for {table}: {sorted(unknown)}")
        own = conn is None
        conn = conn or self._connect()
        try:
            for start in range(0, len(rows), chunk):
                part = rows[start:start + chunk]
                params: dict[str, Any] = {"t": table.upper()}
                tuples = []
                for i, row in enumerate(part):
                    if len(row) != len(columns):
                        raise ValueError("Row length does not match column list.")
                    names = []
                    for j, val in enumerate(row):
                        key = f"p{i}_{j}"
                        params[key] = val
                        names.append("{" + key + "}")
                    tuples.append("(" + ", ".join(names) + ")")
                col_sql = ", ".join(c.upper() for c in columns)  # validated identifiers
                conn.execute(f"INSERT INTO {{t!i}} ({col_sql}) VALUES " + ", ".join(tuples), params)
            return len(rows)
        except (ExasolError, ValueError):
            raise
        except Exception as exc:  # noqa: BLE001
            raise self._classify(exc) from None
        finally:
            if own:
                self._close(conn)

    def run_script(self, script: str, create_schema: bool = False) -> int:
        """Execute a multi-statement SQL script (used by init_db)."""
        conn = self._connect(open_schema=False)
        try:
            if create_schema:
                conn.execute("CREATE SCHEMA IF NOT EXISTS {schema!i}", {"schema": self.settings.schema})
            conn.execute("OPEN SCHEMA {schema!i}", {"schema": self.settings.schema})
            stmts = split_statements(script)
            for stmt in stmts:
                conn.execute(stmt)
            return len(stmts)
        except Exception as exc:  # noqa: BLE001
            raise self._classify(exc) from None
        finally:
            self._close(conn)

    def table_counts(self) -> dict[str, int]:
        out = {}
        for table in TABLE_COLUMNS:
            rows = self.query("SELECT COUNT(*) AS n FROM {t!i}", {"t": table.upper()})
            out[table] = int(rows[0]["n"])
        return out
