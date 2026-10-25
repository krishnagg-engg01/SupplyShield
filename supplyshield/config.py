"""Configuration, identifier validation and assumptions.

Credentials are read ONLY from environment variables (or an ignored local .env
file). They are never sent to the browser and never logged.
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SQL_DIR = ROOT / "sql"

IDENT_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_]{0,62}$")

# Only these tables may ever be addressed by dynamic SQL (bulk inserts, counts).
TABLE_COLUMNS: dict[str, tuple[str, ...]] = {
    "dataset_meta": ("meta_key", "meta_value"),
    "components": ("component_id", "name", "criticality", "unit_cost", "unit"),
    "suppliers": ("supplier_id", "name", "location", "country", "region", "status"),
    "supplier_components": ("supplier_id", "component_id", "unit_price", "lead_time_days", "capacity_per_day"),
    "factories": ("factory_id", "name", "location"),
    "production_lines": ("line_id", "factory_id", "name", "component_id", "daily_output_units", "qty_per_unit", "margin_per_unit"),
    "routes": ("route_id", "name", "origin_region", "destination_factory_id", "via_port", "mode", "transit_days", "cost_per_unit", "status"),
    "inventory": ("factory_id", "component_id", "on_hand_qty", "safety_stock_qty", "reorder_point_qty", "daily_consumption"),
    "shipments": ("shipment_id", "supplier_id", "factory_id", "component_id", "route_id", "quantity", "planned_arrival", "estimated_arrival", "status"),
    "delivery_history": ("delivery_id", "supplier_id", "component_id", "promised_date", "actual_date", "quantity"),
    "disruptions": ("disruption_id", "event_type", "entity_type", "entity_id", "start_date", "duration_days", "severity", "status", "description"),
    "scenario_runs": ("run_id", "created_at", "scenario_type", "params_json", "summary_json", "selected_option", "decision", "decided_at", "note"),
    "recovery_options": ("run_id", "factory_id", "component_id", "option_id", "option_type", "label", "action_cost", "production_loss_cost",
                          "total_cost", "recovery_days", "stockout_days", "unmet_share", "operational_risk", "score", "feasible", "is_recommended", "notes"),
}
SEED_TABLE_ORDER = ["dataset_meta", "components", "suppliers", "supplier_components", "factories", "production_lines",
                    "routes", "inventory", "shipments", "delivery_history", "disruptions"]

# Every number below is an ASSUMPTION, shown in the UI and documented in the README.
ASSUMPTIONS = {
    "horizon_days": 45,   # planning window: only shipments recorded in the data count as supply inside it
    "inbound_statuses": ["SCHEDULED", "IN_TRANSIT", "DELAYED"],
    "alt_surge_share": 0.5,
    "alt_surge_window_days": 30,
    "alt_setup_fee": 15000.0,
    "reroute_handling_days": 2,
    "reroute_fixed_fee": 5000.0,
    "transfer_days": 2,
    "transfer_fixed_fee": 8000.0,
    "transfer_cost_pct_of_unit_cost": 0.03,
    "donor_min_cover_days": 7,
    "expedite_delay_reduction": 0.6,
    "expedite_air_premium_pct": 0.12,
    "expedite_order_price_premium": 0.25,
    "expedite_order_lead_factor": 0.5,
    "approval_threshold": 25000.0,
    "default_budget": 500000.0,
    "currency": "INR",
}

SCORE_WEIGHTS = {"total_cost": 0.30, "recovery_days": 0.20, "production_loss": 0.20, "unmet_share": 0.15, "operational_risk": 0.15}
SUPPLIER_RISK_WEIGHTS = {"on_time": 35, "delay": 15, "lead_time": 20, "capacity": 15, "criticality": 15}
OPERATIONAL_RISK_BASE = {"NO_ACTION": 10, "ALT_SUPPLIER": 40, "REROUTE": 25, "REALLOCATE": 20, "EXPEDITE": 25}


def validate_identifier(name: str, what: str = "identifier") -> str:
    if not isinstance(name, str) or not IDENT_RE.match(name):
        raise ValueError(f"Invalid {what}: {name!r}. Use letters, digits and underscores only (max 63, starting with a letter).")
    return name


def _load_dotenv() -> None:
    try:
        from dotenv import load_dotenv
        load_dotenv(ROOT / ".env", override=False)
    except Exception:
        pass


def _blank_or_placeholder(value: str) -> bool:
    """True for empty values and for untouched .env.example placeholders such as <your-exasol-user>."""
    v = (value or "").strip()
    return not v or (v.startswith("<") and v.endswith(">")) or (v.startswith("<") and ">" in v and "<" in v[1:])


@dataclass(frozen=True)
class ExasolSettings:
    dsn: str = ""
    user: str = ""
    password: str = ""
    schema: str = "SUPPLYSHIELD"
    validate_cert: bool = True
    encryption: bool = True

    def missing(self) -> list[str]:
        """Names of settings that are empty or still hold the <placeholder> text from .env.example."""
        out = []
        if _blank_or_placeholder(self.dsn): out.append("EXASOL_DSN")
        if _blank_or_placeholder(self.user): out.append("EXASOL_USER")
        if _blank_or_placeholder(self.password): out.append("EXASOL_PASSWORD")
        return out

    @property
    def configured(self) -> bool:
        return not self.missing()

    def public(self) -> dict:
        """Safe-to-display view: never contains the password."""
        return {"dsn": self.dsn or None, "user": self.user or None, "schema": self.schema,
                "password_set": bool(self.password), "validate_cert": self.validate_cert,
                "encryption": self.encryption, "missing": self.missing()}


def _truthy(v, default):
    if v is None or str(v).strip() == "":
        return default
    return str(v).strip().lower() in {"1", "true", "yes", "on"}


def get_settings(env: dict | None = None) -> ExasolSettings:
    if env is None:
        _load_dotenv()
        env = os.environ
    schema = (env.get("EXASOL_SCHEMA") or "SUPPLYSHIELD").strip().upper()
    validate_identifier(schema, "EXASOL_SCHEMA")
    return ExasolSettings(
        dsn=(env.get("EXASOL_DSN") or "").strip(),
        user=(env.get("EXASOL_USER") or "").strip(),
        password=env.get("EXASOL_PASSWORD") or "",
        schema=schema,
        validate_cert=_truthy(env.get("EXASOL_VALIDATE_CERT"), True),
        encryption=_truthy(env.get("EXASOL_ENCRYPTION"), True),
    )
