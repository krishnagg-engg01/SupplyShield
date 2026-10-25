# SupplyShield — 3-minute demo script (truthful version)

Say up front which mode you are in. If Exasol is connected, say "live from Exasol"; if not, say "synthetic demo mode" — the banner on every screen shows it.

**0:00–0:25 — Problem.** "A factory operations manager can't quickly see how a supplier or shipment disruption will hit production, inventory and cost, because the data is fragmented. SupplyShield joins it and answers: what breaks first, what are the options, what should we do first?"

**0:25–1:05 — Command Center.** Point at: risk index (click *How is this calculated?*), 2 of 8 positions at stockout risk, earliest stockout in ~18 days, estimated cost *if no action is taken*, recovery delay. Open disruptions: the Shenzhen MicroSemi fab fire. Say: "These are estimates from stated assumptions, not measured losses. The data comes from Exasol views: inventory cover, supplier performance, inbound supply."

**1:05–1:50 — Simulator.** Click *Open in simulator* on the supplier failure. Walk the cascade: supplier → 2 undispatched shipments held → Chennai and Pune MCU stock → drive-unit lines. Show the stock projection chart (grey = no disruption, red = no action, teal = recommended).

**1:50–2:35 — Recovery comparison.** Baseline "no action" first. Alternatives: Taipei ChipWorks, Bengaluru (capacity-limited, partial), transfer from Ahmedabad. Note what is *not* offered and why (Pune is also short, so moving stock only moves the shortage; the incumbent is down so nothing to expedite). Read the score method and the "estimated difference versus baseline" — never "savings". Lower the budget limit to show an option drop out of the recommendation.

**2:35–3:00 — Governance and Exasol.** The recommendation needs human approval (cost above threshold, new supplier). Record a decision — it is stored in Exasol (`SCENARIO_RUNS`), nothing is ordered. Close on Data Source: real `SELECT 1` health check, tables and SQL views used, and what remains uncertain (durations are assumptions; options are evaluated one at a time).

**Never say:** "connected to Exasol" unless the pill is green; "we saved ₹X"; "AI predicts…" (there is no ML model, by design).
