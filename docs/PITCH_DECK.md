# SupplyShield — pitch deck outline (8 slides)

1. **Title** — SupplyShield · Team Vyntrix · ExaThon India 2026 · Track: Factories, Fleets & Supply Chains. *Anticipate disruption. Prevent cascading failures. Recover intelligently.*
2. **Problem** — Operations managers see supplier, shipment, inventory and production data in separate places; by the time a late shipment is noticed, a line may already be 2 weeks from stopping.
3. **Who it is for** — Factory operations / supply-chain planners at multi-plant manufacturers.
4. **Solution** — One view that traces a disruption supplier → shipment → inventory → production line, quantifies exposure, and compares recovery options with a no-action baseline.
5. **How it works (architecture)** — Browser → Flask API → analytics engine (deterministic, explainable) → Exasol (tables + SQL views). Diagram: see README.
6. **Why Exasol** — Cover days, supplier on-time rate, inbound supply, disruption impact and KPI counts are SQL views over operational tables; run history and decisions are written back to `SCENARIO_RUNS` / `RECOVERY_OPTIONS`.
7. **Demo story** — Fab fire at the sole MCU supplier → Chennai stock-out in ~18 days → options: alternative supplier / transfer / (reroute, expedite for shipment events) → recommended option, approval gate.
8. **Honesty & next steps** — Synthetic data labelled as such; estimates not savings; assumptions visible. Next: real ERP/WMS feeds, multi-position combined plans, lane table for transfers, backtest of lead-time uncertainty on real history.
