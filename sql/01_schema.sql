-- SupplyShield schema for Exasol. Run through: python scripts/init_db.py
-- Exasol records PRIMARY/FOREIGN KEY constraints but does not enforce them unless ENABLEd;
-- the seed script and tests verify referential integrity instead. Relationships are documented below.

CREATE TABLE dataset_meta (
    meta_key    VARCHAR(40)   NOT NULL,
    meta_value  VARCHAR(200),
    CONSTRAINT pk_dataset_meta PRIMARY KEY (meta_key)
);

CREATE TABLE components (
    component_id VARCHAR(16)   NOT NULL,
    name         VARCHAR(80)   NOT NULL,
    criticality  DECIMAL(1,0)  NOT NULL,          -- 1 (minor) .. 5 (line stops without it)
    unit_cost    DECIMAL(12,2) NOT NULL,          -- standard cost, INR
    unit         VARCHAR(16)   NOT NULL,
    CONSTRAINT pk_components PRIMARY KEY (component_id)
);

CREATE TABLE suppliers (
    supplier_id VARCHAR(16)  NOT NULL,
    name        VARCHAR(80)  NOT NULL,
    location    VARCHAR(60),
    country     VARCHAR(40),
    region      VARCHAR(20)  NOT NULL,            -- EAST_ASIA | SE_ASIA | INDIA ; routes must match
    status      VARCHAR(12)  NOT NULL,            -- ACTIVE | SUSPENDED
    CONSTRAINT pk_suppliers PRIMARY KEY (supplier_id)
);

-- Which supplier can deliver which component, at what price / lead time (door to door) / capacity.
CREATE TABLE supplier_components (
    supplier_id      VARCHAR(16)   NOT NULL,      -- FK -> suppliers
    component_id     VARCHAR(16)   NOT NULL,      -- FK -> components
    unit_price       DECIMAL(12,2) NOT NULL,
    lead_time_days   DECIMAL(4,0)  NOT NULL,
    capacity_per_day DECIMAL(12,0) NOT NULL,
    CONSTRAINT pk_supplier_components PRIMARY KEY (supplier_id, component_id)
);

CREATE TABLE factories (
    factory_id VARCHAR(16) NOT NULL,
    name       VARCHAR(80) NOT NULL,
    location   VARCHAR(60),
    CONSTRAINT pk_factories PRIMARY KEY (factory_id)
);

-- A line depends on exactly one critical component (documented simplification).
CREATE TABLE production_lines (
    line_id            VARCHAR(16)   NOT NULL,
    factory_id         VARCHAR(16)   NOT NULL,    -- FK -> factories
    name               VARCHAR(80)   NOT NULL,
    component_id       VARCHAR(16)   NOT NULL,    -- FK -> components
    daily_output_units DECIMAL(12,0) NOT NULL,
    qty_per_unit       DECIMAL(6,2)  NOT NULL,    -- components consumed per finished unit
    margin_per_unit    DECIMAL(12,2) NOT NULL,    -- contribution margin lost per unit not built, INR
    CONSTRAINT pk_production_lines PRIMARY KEY (line_id)
);

CREATE TABLE routes (
    route_id               VARCHAR(16)   NOT NULL,
    name                   VARCHAR(100)  NOT NULL,
    origin_region          VARCHAR(20)   NOT NULL,
    destination_factory_id VARCHAR(16)   NOT NULL, -- FK -> factories
    via_port               VARCHAR(40),            -- NULL for domestic road
    mode                   VARCHAR(8)    NOT NULL, -- SEA | AIR | ROAD
    transit_days           DECIMAL(4,0)  NOT NULL,
    cost_per_unit          DECIMAL(10,2) NOT NULL, -- freight, INR per component unit
    status                 VARCHAR(8)    NOT NULL, -- OPEN | CLOSED
    CONSTRAINT pk_routes PRIMARY KEY (route_id)
);

CREATE TABLE inventory (
    factory_id        VARCHAR(16)   NOT NULL,     -- FK -> factories
    component_id      VARCHAR(16)   NOT NULL,     -- FK -> components
    on_hand_qty       DECIMAL(12,0) NOT NULL,
    safety_stock_qty  DECIMAL(12,0) NOT NULL,
    reorder_point_qty DECIMAL(12,0) NOT NULL,
    daily_consumption DECIMAL(12,2) NOT NULL,
    CONSTRAINT pk_inventory PRIMARY KEY (factory_id, component_id)
);

CREATE TABLE shipments (
    shipment_id       VARCHAR(16)   NOT NULL,
    supplier_id       VARCHAR(16)   NOT NULL,     -- FK -> suppliers
    factory_id        VARCHAR(16)   NOT NULL,     -- FK -> factories
    component_id      VARCHAR(16)   NOT NULL,     -- FK -> components
    route_id          VARCHAR(16),                -- FK -> routes
    quantity          DECIMAL(12,0) NOT NULL,
    planned_arrival   DATE          NOT NULL,
    estimated_arrival DATE          NOT NULL,
    status            VARCHAR(12)   NOT NULL,     -- SCHEDULED | IN_TRANSIT | DELAYED | DELIVERED | CANCELLED
    CONSTRAINT pk_shipments PRIMARY KEY (shipment_id)
);

CREATE TABLE delivery_history (
    delivery_id   VARCHAR(16)   NOT NULL,
    supplier_id   VARCHAR(16)   NOT NULL,         -- FK -> suppliers
    component_id  VARCHAR(16)   NOT NULL,         -- FK -> components
    promised_date DATE          NOT NULL,
    actual_date   DATE          NOT NULL,
    quantity      DECIMAL(12,0) NOT NULL,
    CONSTRAINT pk_delivery_history PRIMARY KEY (delivery_id)
);

CREATE TABLE disruptions (
    disruption_id VARCHAR(16)   NOT NULL,
    event_type    VARCHAR(24)   NOT NULL,         -- SUPPLIER_FAILURE | PORT_CLOSURE | SHIPMENT_DELAY | INVENTORY_SHORTAGE
    entity_type   VARCHAR(12)   NOT NULL,         -- SUPPLIER | PORT | SHIPMENT | INVENTORY
    entity_id     VARCHAR(40)   NOT NULL,
    start_date    DATE          NOT NULL,
    duration_days DECIMAL(4,0),                   -- planning estimate; NULL if unknown
    severity      VARCHAR(10)   NOT NULL,
    status        VARCHAR(10)   NOT NULL,         -- OPEN | RESOLVED
    description   VARCHAR(400),
    CONSTRAINT pk_disruptions PRIMARY KEY (disruption_id)
);

-- Simulation history and the human decision recorded for it (nothing is executed externally).
CREATE TABLE scenario_runs (
    run_id          VARCHAR(40)   NOT NULL,
    created_at      TIMESTAMP     NOT NULL,
    scenario_type   VARCHAR(30)   NOT NULL,
    params_json     VARCHAR(4000),
    summary_json    VARCHAR(8000),
    selected_option VARCHAR(40),
    decision        VARCHAR(12),                  -- PENDING | APPROVED | REJECTED | DEFERRED
    decided_at      TIMESTAMP,
    note            VARCHAR(500),
    CONSTRAINT pk_scenario_runs PRIMARY KEY (run_id)
);

CREATE TABLE recovery_options (
    run_id               VARCHAR(40)   NOT NULL,  -- FK -> scenario_runs
    factory_id           VARCHAR(16)   NOT NULL,
    component_id         VARCHAR(16)   NOT NULL,
    option_id            VARCHAR(40)   NOT NULL,
    option_type          VARCHAR(16)   NOT NULL,
    label                VARCHAR(160),
    action_cost          DECIMAL(14,2),
    production_loss_cost DECIMAL(14,2),
    total_cost           DECIMAL(14,2),
    recovery_days        DECIMAL(6,1),
    stockout_days        DECIMAL(8,2),
    unmet_share          DECIMAL(6,4),
    operational_risk     DECIMAL(5,1),
    score                DECIMAL(6,1),
    feasible             DECIMAL(1,0),
    is_recommended       DECIMAL(1,0),
    notes                VARCHAR(600),
    CONSTRAINT pk_recovery_options PRIMARY KEY (run_id, factory_id, component_id, option_id)
);
