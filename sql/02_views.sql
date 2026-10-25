-- Analytics views. Re-runnable (CREATE OR REPLACE). Run through: python scripts/init_db.py

-- Inventory cover: usable stock / daily consumption (NULL when consumption is not positive).
CREATE OR REPLACE VIEW v_inventory_position AS
SELECT i.factory_id,
       i.component_id,
       c.name AS component_name,
       c.criticality,
       i.on_hand_qty,
       CASE WHEN i.on_hand_qty > 0 THEN i.on_hand_qty ELSE 0 END AS usable_stock,
       i.safety_stock_qty,
       i.reorder_point_qty,
       i.daily_consumption,
       CASE WHEN i.daily_consumption > 0
            THEN CAST((CASE WHEN i.on_hand_qty > 0 THEN i.on_hand_qty ELSE 0 END) / i.daily_consumption AS DECIMAL(12,2))
       END AS cover_days,
       CASE WHEN i.on_hand_qty <= i.reorder_point_qty THEN 1 ELSE 0 END AS below_reorder
FROM inventory i
JOIN components c ON c.component_id = i.component_id;

-- Supplier delivery performance from history (on-time = delivered on or before the promised date).
CREATE OR REPLACE VIEW v_supplier_performance AS
SELECT supplier_id,
       COUNT(*) AS n_deliveries,
       CAST(AVG(CASE WHEN actual_date <= promised_date THEN 1 ELSE 0 END) AS DECIMAL(6,4)) AS on_time_rate,
       CAST(AVG(GREATEST(DAYS_BETWEEN(actual_date, promised_date), 0)) AS DECIMAL(8,2)) AS avg_delay_days
FROM delivery_history
GROUP BY supplier_id;

-- Open inbound commitments per supplier (used for the capacity-utilisation factor).
CREATE OR REPLACE VIEW v_supplier_commitment AS
SELECT supplier_id,
       COUNT(*) AS open_shipments,
       SUM(quantity) AS open_qty
FROM shipments
WHERE status IN ('SCHEDULED', 'IN_TRANSIT', 'DELAYED')
GROUP BY supplier_id;

-- Inbound supply per factory / component.
CREATE OR REPLACE VIEW v_inbound_supply AS
SELECT factory_id,
       component_id,
       COUNT(*) AS open_shipments,
       SUM(quantity) AS inbound_qty,
       MIN(estimated_arrival) AS next_eta,
       SUM(CASE WHEN estimated_arrival > planned_arrival THEN quantity ELSE 0 END) AS delayed_qty
FROM shipments
WHERE status IN ('SCHEDULED', 'IN_TRANSIT', 'DELAYED')
GROUP BY factory_id, component_id;

-- Shipments touched by an OPEN disruption (supplier, port or single-shipment events).
CREATE OR REPLACE VIEW v_disruption_impact AS
SELECT d.disruption_id,
       d.event_type,
       s.shipment_id,
       s.supplier_id,
       s.factory_id,
       s.component_id,
       s.quantity,
       s.planned_arrival,
       s.estimated_arrival,
       DAYS_BETWEEN(s.estimated_arrival, s.planned_arrival) AS delay_days
FROM disruptions d
JOIN shipments s ON s.status IN ('SCHEDULED', 'IN_TRANSIT', 'DELAYED')
LEFT JOIN routes r ON r.route_id = s.route_id
WHERE d.status = 'OPEN'
  AND (   (d.entity_type = 'SUPPLIER' AND s.supplier_id = d.entity_id)
       OR (d.entity_type = 'SHIPMENT' AND s.shipment_id = d.entity_id)
       OR (d.entity_type = 'PORT'     AND r.via_port    = d.entity_id));

-- Candidate suppliers per component, joined with delivery performance (feeds recovery options).
CREATE OR REPLACE VIEW v_alt_supplier_candidates AS
SELECT sc.component_id,
       sc.supplier_id,
       s.name AS supplier_name,
       s.status AS supplier_status,
       sc.unit_price,
       sc.lead_time_days,
       sc.capacity_per_day,
       p.on_time_rate,
       p.avg_delay_days
FROM supplier_components sc
JOIN suppliers s ON s.supplier_id = sc.supplier_id
LEFT JOIN v_supplier_performance p ON p.supplier_id = sc.supplier_id;

-- Single-row KPI counts for the Command Center.
CREATE OR REPLACE VIEW v_dashboard_kpis AS
SELECT (SELECT COUNT(*) FROM disruptions WHERE status = 'OPEN') AS open_disruptions,
       (SELECT COUNT(*) FROM v_inventory_position WHERE below_reorder = 1) AS below_reorder_positions,
       (SELECT COUNT(*) FROM shipments WHERE status IN ('SCHEDULED', 'IN_TRANSIT', 'DELAYED')
                                         AND estimated_arrival > planned_arrival) AS delayed_shipments,
       (SELECT COALESCE(SUM(quantity), 0) FROM shipments WHERE status IN ('SCHEDULED', 'IN_TRANSIT', 'DELAYED')) AS inbound_qty
FROM DUAL;

-- Saved recovery-plan comparison with the decision recorded for each run.
CREATE OR REPLACE VIEW v_recovery_comparison AS
SELECT r.run_id, r.created_at, r.scenario_type, r.decision, r.selected_option,
       o.factory_id, o.component_id, o.option_id, o.option_type, o.label,
       o.action_cost, o.production_loss_cost, o.total_cost, o.recovery_days,
       o.stockout_days, o.unmet_share, o.operational_risk, o.score, o.feasible, o.is_recommended
FROM scenario_runs r
JOIN recovery_options o ON o.run_id = r.run_id;
