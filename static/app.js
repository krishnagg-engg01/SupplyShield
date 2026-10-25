/* SupplyShield front-end. Talks only to the local backend API; no credentials ever touch the browser. */
'use strict';
const $ = (s, r = document) => r.querySelector(s);
const esc = v => String(v ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const IC = {
  grid:'<rect x="3" y="3" width="7" height="9" rx="1.5"/><rect x="14" y="3" width="7" height="5" rx="1.5"/><rect x="14" y="12" width="7" height="9" rx="1.5"/><rect x="3" y="16" width="7" height="5" rx="1.5"/>',
  flask:'<path d="M9 3h6M10 3v6L4.5 19a1.5 1.5 0 001.3 2.2h12.4a1.5 1.5 0 001.3-2.2L14 9V3"/><path d="M7.5 15h9"/>',
  log:'<path d="M8 6h12M8 12h12M8 18h12M3.5 6h.01M3.5 12h.01M3.5 18h.01"/>',
  db:'<ellipse cx="12" cy="5.5" rx="8" ry="3"/><path d="M4 5.5v13c0 1.7 3.6 3 8 3s8-1.3 8-3v-13M4 12c0 1.7 3.6 3 8 3s8-1.3 8-3"/>',
  factory:'<path d="M3 21V10l6 4V10l6 4V6h3v15z"/><path d="M3 21h18"/>',
  ship:'<path d="M3 17l2 3h14l2-3M5 17l1.5-6h11L19 17M12 11V5h3"/>',
  box:'<path d="M3.5 7.5L12 3l8.5 4.5v9L12 21l-8.5-4.5z"/><path d="M3.5 7.5L12 12l8.5-4.5M12 12v9"/>',
  alert:'<path d="M12 3l10 18H2z"/><path d="M12 10v5M12 18h.01"/>',
  port:'<circle cx="12" cy="5" r="2"/><path d="M12 7v14M5 13a7 7 0 0014 0M8 12H5M19 12h-3"/>',
};
const icon = (n, cls = '') => `<svg viewBox="0 0 24 24" class="${cls}">${IC[n]}</svg>`;
const SCEN = {
  supplier_failure: {name: 'Supplier failure', ic: 'factory', desc: 'A critical supplier cannot deliver a component.'},
  shipment_disruption: {name: 'Shipment disruption', ic: 'ship', desc: 'Shipments are delayed, or a port / route becomes unavailable.'},
  inventory_shortage: {name: 'Inventory shortage', ic: 'box', desc: 'Stock is lost or demand surges at a factory.'},
};
const OPT_TYPE = {NO_ACTION: 'Baseline', ALT_SUPPLIER: 'Alt. supplier', REROUTE: 'Reroute', REALLOCATE: 'Reallocate', EXPEDITE: 'Expedite'};
const S = {view: 'overview', status: null, dash: null, ents: null, runs: null, tab: 'inventory', busy: false, error: null,
           sim: {scenario: 'supplier_failure', params: {}, budget: 500000, result: null, pair: 0, error: null, decision: null, running: false, subtype: 'delay'}};

/* ---------- formatting ---------- */
const nf = new Intl.NumberFormat('en-IN', {maximumFractionDigits: 0});
const inr = n => { if (n == null || isNaN(n)) return '—'; const a = Math.abs(n), s = n < 0 ? '−' : '';
  if (a >= 1e7) return `${s}₹${(a / 1e7).toFixed(2)} Cr`; if (a >= 1e5) return `${s}₹${(a / 1e5).toFixed(2)} L`; return `${s}₹${nf.format(a)}`; };
const inrFull = n => (n == null ? '—' : '₹' + nf.format(n));
const dd = (n, p = 1) => (n == null ? '—' : Number(n).toFixed(p));
const sgn = (n, p = 1, u = '') => (n == null ? '—' : (n > 0 ? '+' : n < 0 ? '−' : '±') + Math.abs(n).toFixed(p) + u);
const tipEl = t => `<span class="tip" title="${esc(t)}">?</span>`;
const bandCls = b => ({LOW: 'teal', MODERATE: 'amber', HIGH: 'red', CRITICAL: 'red', UNKNOWN: 'dim'}[b] || 'dim');
const dateAdd = (asOf, off) => { if (off == null) return '—'; const d = new Date(asOf + 'T00:00:00'); d.setDate(d.getDate() + off); return d.toLocaleDateString('en-IN', {day: '2-digit', month: 'short'}); };

/* ---------- API ---------- */
async function api(path, body) {
  const opt = body === undefined ? {} : {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(body)};
  let res;
  try { res = await fetch(path, opt); } catch { throw {message: 'Cannot reach the SupplyShield backend. Is "python app.py" still running?', details: []}; }
  const j = await res.json().catch(() => ({}));
  if (!res.ok) { if (j.status) S.status = j.status; throw {message: j.error || 'Request failed', hint: j.hint, details: j.details || [], status: res.status}; }
  return j;
}

/* ---------- chrome ---------- */
const NAV = [['overview', 'Command Center', 'grid'], ['simulator', 'Simulator & Recovery', 'flask'], ['log', 'Decision Log', 'log'], ['source', 'Data Source', 'db']];
function renderChrome() {
  $('#nav').innerHTML = NAV.map(([k, l, i]) => `<button class="nav ${S.view === k ? 'on' : ''}" data-act="view" data-v="${k}">${icon(i)}${l}</button>`).join('');
  $('#crumb').textContent = (NAV.find(n => n[0] === S.view) || [])[1] || '';
  const st = S.status; if (!st) return;
  const m = {connected: ['live', 'Exasol · connected'], demo: ['demo', 'SYNTHETIC DEMO DATA'], error: ['err', 'Exasol · connection error'], not_configured: ['idle', 'Exasol · not configured'], idle: ['idle', 'No data source']}[st.ui_state];
  $('#mode-pill').innerHTML = `<span class="pill ${m[0]}"><span class="dot"></span><b>${m[1]}</b></span>`;
  $('#refresh-info').textContent = st.last_refresh_at ? 'Last refresh ' + new Date(st.last_refresh_at).toLocaleTimeString('en-IN') : 'No data loaded';
  $('#banner').innerHTML = st.ui_state === 'demo'
    ? `<div class="banner demo">⚠ SYNTHETIC DEMO MODE — all figures come from invented data generated in memory. Nothing on this screen was read from Exasol.</div>`
    : st.ui_state === 'connected' ? `<div class="banner" style="background:rgba(56,224,200,.06);color:var(--teal)">Live from Exasol · dataset label: <b>${esc(st.dataset?.label || 'unlabelled')}</b>${st.dataset?.label === 'SYNTHETIC' ? ' (synthetic rows stored in Exasol)' : ''} · as of ${esc(st.dataset?.as_of || '—')}</div>`
    : st.ui_state === 'error' ? `<div class="banner err">Exasol connection error — no data is being shown. Demo data is never substituted automatically.</div>` : '';
}
const hasData = () => S.status && (S.status.ui_state === 'connected' || S.status.ui_state === 'demo');
const loading = t => `<div class="loading"><span class="spin"></span> ${esc(t)}</div>`;
function gate() {
  const st = S.status, c = st.connection;
  const msg = st.ui_state === 'error' ? `<div class="alert err"><b>Connection error.</b> ${esc(c.message)}</div>`
    : `<div class="alert info"><b>No data source is active.</b> Exasol is not configured yet.</div>`;
  return `<h2 class="title">Choose a data source</h2><p class="sub">SupplyShield never mixes live and demo results. Connect to Exasol, or explicitly explore with clearly labelled synthetic demo data.</p>
  <div class="card">${msg}<div class="row mt"><button class="btn pri" data-act="demo">Explore with SYNTHETIC demo data</button><button class="btn out" data-act="test">Test Exasol connection</button><button class="btn out" data-act="view" data-v="source">Setup instructions</button></div></div>`;
}

/* ---------- Command Center ---------- */
function gaugeSvg(v, band) {
  const R = 62, C = 2 * Math.PI * R, col = {teal: '#38e0c8', amber: '#f2b04a', red: '#ef5b5b', dim: '#5d6c8a'}[bandCls(band)];
  return `<svg width="170" height="170" viewBox="0 0 170 170"><defs><linearGradient id="gg" x1="0" x2="1"><stop offset="0" stop-color="${col}" stop-opacity=".5"/><stop offset="1" stop-color="${col}"/></linearGradient></defs>
  <circle cx="85" cy="85" r="${R}" fill="none" stroke="#1a2540" stroke-width="12"/><circle cx="85" cy="85" r="${R}" fill="none" stroke="url(#gg)" stroke-width="12" stroke-linecap="round"
  stroke-dasharray="${(C * v / 100).toFixed(1)} ${C.toFixed(1)}" transform="rotate(-90 85 85)"/><text x="85" y="92" text-anchor="middle" fill="#e8edf7" font-family="IBM Plex Mono" font-size="38" font-weight="600">${Math.round(v)}</text>
  <text x="85" y="112" text-anchor="middle" fill="#5d6c8a" font-family="IBM Plex Mono" font-size="10">of 100</text></svg>`;
}
function timeline(d) {
  const H = 45, pos = d.positions.filter(p => p.assessable).sort((a, b) => (a.disrupted?.stockout_in_days ?? 999) - (b.disrupted?.stockout_in_days ?? 999));
  const rows = pos.map(p => {
    const so = p.disrupted.stockout_in_days, rec = p.disrupted.recovery_day;
    const okW = Math.min(so ?? H, H) / H * 100, badL = so == null ? 0 : so / H * 100, badW = so == null ? 0 : (Math.min(rec, H) - so) / H * 100;
    const ticks = p.arrivals.filter(a => a.eta < H).map(a => `<i class="tick" style="left:${a.eta / H * 100}%" title="${esc(a.shipment_id)}: ${nf.format(a.qty)} pcs, day ${a.eta}"></i>`).join('');
    return `<div><b>${esc(p.component)}</b><div class="hint">${esc(p.factory)}</div></div>
      <div class="track"><div class="seg-ok" style="left:0;width:${okW}%"></div>${so == null ? '' : `<div class="seg-bad" style="left:${badL}%;width:${Math.max(badW, 1.5)}%"></div>`}${ticks}</div>
      <div class="num ${so == null ? 'c-dim' : 'c-red'}" style="text-align:right">${so == null ? 'covered' : dd(so) + ' d'}</div>`;
  }).join('');
  return `<div class="tl">${rows}</div><div class="axis"><div></div><div class="s"><span>today</span><span>+15 d</span><span>+30 d</span><span>+45 d</span></div><div></div></div>
  <div class="legend"><span><i style="background:var(--teal)"></i>stock covers demand</span><span><i style="background:var(--red)"></i>projected stockout until supply resumes</span><span><i style="background:#fff;width:2px;height:10px"></i>recorded shipment arrival</span></div>`;
}
function tabTable(d) {
  const T = S.tab, asOf = d.as_of;
  if (T === 'inventory') return d.alerts.length ? `<div class="tw"><table><thead><tr><th>Position</th><th class="r">On hand</th><th class="r">Daily use</th><th class="r">Cover (d)</th><th class="r">Reorder pt</th><th class="r">Stockout in</th><th>Alert</th></tr></thead><tbody>${d.alerts.map(p => `<tr>
    <td><b>${esc(p.component)}</b><div class="hint">${esc(p.factory)}</div></td><td class="r num">${nf.format(p.on_hand)}</td><td class="r num">${nf.format(p.daily_consumption)}</td><td class="r num">${dd(p.cover_days)}</td><td class="r num">${nf.format(p.reorder_point)}</td>
    <td class="r num ${p.at_risk ? 'c-red' : ''}">${p.at_risk ? dd(p.disrupted.stockout_in_days) + ' d' : '—'}</td><td>${p.at_risk ? '<span class="tag t-red">stockout risk</span> ' : ''}${p.below_reorder ? '<span class="tag t-amber">below reorder point</span>' : ''}${!p.at_risk && !p.below_reorder ? '<span class="tag t-dim">low cover</span>' : ''}</td></tr>`).join('')}</tbody></table></div>` : '<div class="empty">No inventory alerts.</div>';
  if (T === 'lines') return d.lines.length ? `<div class="tw"><table><thead><tr><th>Line</th><th>Fed by</th><th class="r">Output/day</th><th class="r">Stockout in</th><th class="r">Output lost*</th><th class="r">Est. margin lost*</th></tr></thead><tbody>${d.lines.map(l => `<tr>
    <td><b>${esc(l.name)}</b><div class="hint">${esc(l.factory)}</div></td><td>${esc(l.component)}</td><td class="r num">${nf.format(l.daily_output_units)}</td><td class="r num c-red">${dd(l.stockout_in_days)} d</td><td class="r num">${nf.format(l.lost_output_units)}</td><td class="r num">${inr(l.loss_cost)}</td></tr>`).join('')}</tbody></table></div><p class="hint">*No-action estimate: stockout-equivalent days × daily output × margin per unit. An estimate, not a measured loss.</p>` : '<div class="empty">No production line is currently projected to stop.</div>';
  if (T === 'suppliers') return `<div class="tw"><table><thead><tr><th>Supplier</th><th class="r">Risk score ${tipEl('0-100, higher = riskier. Weighted from on-time rate, average delay, lead time, capacity utilisation and component criticality. Missing factors are skipped and weights re-normalised.')}</th><th class="r">On-time</th><th class="r">Avg delay</th><th class="r">Open shipments</th><th>Status</th></tr></thead><tbody>${d.suppliers.map(s => `<tr>
    <td><b>${esc(s.name)}</b><div class="hint">${esc(s.supplier_id)}</div></td><td class="r num">${s.score == null ? 'n/a' : dd(s.score)} <span class="tag t-${bandCls(s.band)}">${s.band}</span></td><td class="r num">${s.on_time_rate == null ? '—' : Math.round(s.on_time_rate * 100) + '%'}</td><td class="r num">${s.avg_delay_days == null ? '—' : dd(s.avg_delay_days) + ' d'}</td><td class="r num">${s.open_shipments}</td>
    <td>${s.disrupted ? '<span class="tag t-red">open disruption</span>' : '<span class="tag t-dim">active</span>'}${s.missing.length ? ` <span class="hint" title="Missing factors: ${esc(s.missing.join(', '))}">partial data</span>` : ''}</td></tr>`).join('')}</tbody></table></div>`;
  return d.shipments.length ? `<div class="tw"><table><thead><tr><th>Shipment</th><th>Supplier</th><th>To</th><th class="r">Qty</th><th class="r">Planned</th><th class="r">ETA</th><th class="r">Delay</th></tr></thead><tbody>${d.shipments.map(s => `<tr>
    <td class="num">${esc(s.shipment_id)}</td><td>${esc(s.supplier_id)}</td><td>${esc(s.factory_id)} · ${esc(s.component_id)}</td><td class="r num">${nf.format(s.qty)}</td><td class="r num">${dateAdd(asOf, s.planned_day)}</td>
    <td class="r num">${s.eta_day == null ? '—' : dateAdd(asOf, s.eta_day)}</td><td class="r num ${s.delay_days == null || s.delay_days > 5 ? 'c-red' : 'c-amber'}">${s.status === 'CANCELLED' ? 'cancelled' : '+' + s.delay_days + ' d'}</td></tr>`).join('')}</tbody></table></div><p class="hint">Delays include effects of open disruptions applied by the model (day-based ETAs).</p>` : '<div class="empty">No late shipments.</div>';
}
function viewOverview() {
  const d = S.dash; if (!d) return loading('Querying the active dataset…');
  const k = d.kpis, r = d.risk, A = d.assumptions.assumptions;
  const names = {SUPPLIER_FAILURE: ['factory', 'Supplier failure'], PORT_CLOSURE: ['port', 'Port closure'], SHIPMENT_DELAY: ['ship', 'Shipment delay'], INVENTORY_SHORTAGE: ['box', 'Inventory shortage']};
  const first = d.positions.filter(p => p.at_risk).sort((a, b) => a.disrupted.stockout_in_days - b.disrupted.stockout_in_days)[0];
  return `<h2 class="title">Command Center</h2><p class="sub">Where supplier and shipment disruptions will hit production first, what it is estimated to cost, and what to do next. Reference date: <b>${esc(d.as_of)}</b>.</p>
  <div class="grid hero">
    <div class="card gauge"><div class="hint" style="margin-bottom:6px">Supply-chain risk index ${tipEl(r.explanation)}</div>${gaugeSvg(r.index, r.band)}<div class="band c-${bandCls(r.band)}">${r.band}</div>
      <details style="width:100%;text-align:left"><summary>How is this calculated?</summary><p class="hint">${esc(r.explanation)}</p>
      <table><tbody>${Object.entries(r.parts).map(([n, v]) => `<tr><td>${n.replace(/_/g, ' ')}</td><td class="r num">${v == null ? 'n/a' : dd(v * 100) + '%'}</td><td class="r num c-dim">× ${r.weights[n]}</td></tr>`).join('')}</tbody></table></details></div>
    <div class="grid k4">
      <div class="card kpi red"><div class="lbl">Positions at stockout risk ${tipEl('Factory/component positions whose usable stock plus recorded inbound shipments cannot meet projected consumption inside the 45-day window.')}</div><div class="num ${k.at_risk_positions ? 'c-red' : 'c-teal'}">${k.at_risk_positions}<span class="c-dim" style="font-size:18px"> / ${k.total_positions}</span></div><div class="foot">${k.below_reorder} below reorder point · ${k.delayed_shipments_recorded} delayed shipments on record</div></div>
      <div class="card kpi amber"><div class="lbl">Earliest projected stockout ${tipEl('Time until usable stock runs out, counting only shipments that arrive before that moment.')}</div><div class="num c-amber">${k.earliest_stockout_days == null ? '—' : dd(k.earliest_stockout_days) + ' d'}</div><div class="foot">${first ? esc(first.component) + ' · ' + esc(first.factory) : 'No stockout projected'}</div></div>
      <div class="card kpi"><div class="lbl">Est. disruption cost, no action ${tipEl('Estimated margin lost on production lines that stop = stockout-equivalent days × daily output × margin per unit. Assumption-based, not a measured loss.')}</div><div class="num">${inr(k.no_action_cost)}</div><div class="foot">estimate${k.cost_complete ? '' : ' (some lines unmapped)'} · margin-based</div></div>
      <div class="card kpi"><div class="lbl">Expected recovery delay ${tipEl('Days from today until supply resumes for the last affected position (planning-window capped at 45).')}</div><div class="num">${k.expected_recovery_delay_days}<span class="c-dim" style="font-size:18px"> days</span></div><div class="foot">if no action is taken · duration is a planning assumption</div></div>
    </div>
  </div>
  <div class="grid two mt">
    <div class="card"><h3>Open disruptions <span class="tag t-dim">${k.open_disruptions}</span></h3><p class="hint">Recorded events. Supplier failures and port closures are applied to the model; delay records are already reflected in shipment ETAs.</p>
      ${d.disruptions.length ? d.disruptions.map(e => { const n = names[e.event_type] || ['alert', e.event_type]; return `<div class="item"><div class="ic c-${e.severity === 'CRITICAL' ? 'red' : 'amber'}">${icon(n[0])}</div><div class="body"><b>${n[1]}</b> · ${esc(e.entity_id)} <span class="tag t-${e.severity === 'CRITICAL' ? 'red' : 'amber'}">${esc(e.severity)}</span>
        <div class="hint">${esc(e.description)}</div><div class="meta">since ${esc(e.start_date)}${e.duration_days ? ' · est. ' + e.duration_days + ' d' : ''} · ${e.applied_in_model ? 'applied in model' : 'informational'}</div>
        ${e.simulate ? `<button class="btn out sm" style="margin-top:8px" data-act="load-disruption" data-id="${esc(e.disruption_id)}">Open in simulator →</button>` : ''}</div></div>`; }).join('') : '<div class="empty">No open disruptions.</div>'}</div>
    <div class="card"><h3>Recommended next actions</h3><p class="hint">Top-scoring option per at-risk position (default budget ${inr(A.default_budget)}). Recommendations only — nothing is ordered or changed.</p>
      ${d.actions.length ? d.actions.map(a => `<div class="item"><div class="ic c-teal">${icon('alert')}</div><div class="body"><b>${esc(a.component)}</b> · ${esc(a.factory)} <span class="tag t-red">stockout in ${dd(a.stockout_in_days)} d</span>
        <div>${a.recommended ? esc(a.recommended.label) : 'No confident recommendation'}</div><div class="meta">${a.recommended ? 'action cost ' + inr(a.recommended.action_cost) + ' · ' + (a.recommended.approval_required ? 'human approval required' : 'planner review') : esc(a.message)}</div></div></div>`).join('') + `<button class="btn pri sm" style="margin-top:12px" data-act="view" data-v="simulator">Compare all options →</button>` : '<div class="empty">No position needs action under current data.</div>'}</div>
  </div>
  <div class="card mt"><h3>Stockout timeline by position ${tipEl('Per factory/component: how long usable stock lasts, and the gap until the next recorded shipment can actually arrive.')}</h3><p class="hint">Projection over the 45-day planning window using only shipments recorded in the data.</p><div style="margin-top:14px">${timeline(d)}</div></div>
  <div class="card mt"><div class="tabs">${[['inventory', 'Inventory alerts'], ['lines', 'Production lines'], ['suppliers', 'Suppliers'], ['shipments', 'Late shipments']].map(([t, l]) => `<button class="tabbtn ${S.tab === t ? 'on' : ''}" data-act="tab" data-t="${t}">${l}</button>`).join('')}</div>${tabTable(d)}</div>
  <details class="mt"><summary>Assumptions behind these numbers</summary>${assumptionsTable(d.assumptions)}</details>`;
}
function assumptionsTable(a) {
  const A = a.assumptions, rows = [['Planning window', A.horizon_days + ' days; only recorded shipments count as supply'], ['Currency', A.currency],
    ['Alt. supplier surge', `${A.alt_surge_share * 100}% of daily capacity for ${A.alt_surge_window_days} d`], ['Alt. supplier setup fee', inrFull(A.alt_setup_fee)], ['Re-booking time for reroutes', A.reroute_handling_days + ' d + ' + inrFull(A.reroute_fixed_fee)],
    ['Inter-factory transfer', `${A.transfer_days} d, ${inrFull(A.transfer_fixed_fee)} + ${A.transfer_cost_pct_of_unit_cost * 100}% of unit cost per pc`], ['Donor factory reserve', `max(safety stock, ${A.donor_min_cover_days} days of cover)`],
    ['Expedite delay recovery', A.expedite_delay_reduction * 100 + '% of added delay; ' + A.expedite_air_premium_pct * 100 + '% air premium'], ['Expedited order', `lead time ×${A.expedite_order_lead_factor}, price +${A.expedite_order_price_premium * 100}%`], ['Human approval above', inrFull(A.approval_threshold)],
    ['Score weights', Object.entries(a.score_weights).map(([k, v]) => `${k.replace(/_/g, ' ')} ${v * 100}%`).join(' · ')],
    ['Supplier risk weights', Object.entries(a.supplier_risk_weights).map(([k, v]) => `${k.replace(/_/g, ' ')} ${v}`).join(' · ')]];
  return `<table><tbody>${rows.map(([k, v]) => `<tr><td style="width:240px;color:var(--dim)">${k}</td><td>${esc(v)}</td></tr>`).join('')}</tbody></table><p class="hint">Every value is a documented assumption (see README), not a measurement. Material needed anyway is not counted as cost — only premiums and fees.</p>`;
}

/* ---------- Simulator ---------- */
function paramForm() {
  const e = S.ents, s = S.sim, p = s.params;
  const opt = (arr, key, lab, sel) => arr.map(x => `<option value="${esc(x[key])}" ${x[key] === sel ? 'selected' : ''}>${esc(x[lab])}</option>`).join('');
  const num = (f, min, max, step = 1) => `<input type="number" data-field="${f}" min="${min}" max="${max}" step="${step}" value="${esc(p[f] ?? '')}">`;
  if (s.scenario === 'supplier_failure') {
    const sup = e.suppliers.find(x => x.supplier_id === p.supplier_id);
    return `<label class="f">Failed supplier</label><select data-field="supplier_id"><option value="">Select…</option>${opt(e.suppliers, 'supplier_id', 'name', p.supplier_id)}</select>
    <label class="f">Component affected</label><select data-field="component_id"><option value="">All components of this supplier</option>${(sup ? sup.components : []).map(c => `<option ${c === p.component_id ? 'selected' : ''} value="${c}">${esc(e.components.find(x => x.component_id === c)?.name || c)}</option>`).join('')}</select>
    <label class="f">Outage duration (days) ${tipEl('Planning assumption: how long before the supplier can dispatch again.')}</label>${num('outage_days', 1, 120)}
    <label class="check"><input type="checkbox" data-field="cancel_open_shipments" ${p.cancel_open_shipments ? 'checked' : ''}> Undispatched shipments are cancelled (not just delayed)</label>`;
  }
  if (s.scenario === 'shipment_disruption') {
    const port = s.subtype === 'port_closure';
    return `<div class="seg" style="margin-top:14px"><button data-act="subtype" data-v="delay" class="${!port ? 'on' : ''}">Shipment delay</button><button data-act="subtype" data-v="port_closure" class="${port ? 'on' : ''}">Port / route closure</button></div>` + (port
      ? `<label class="f">Closed port</label><select data-field="port"><option value="">Select…</option>${e.ports.map(x => `<option ${x === p.port ? 'selected' : ''}>${esc(x)}</option>`).join('')}</select><label class="f">Closure duration (days)</label>${num('closure_days', 1, 120)}`
      : `<label class="f">Delayed shipments (Ctrl/Cmd-click for several)</label><select multiple data-field="shipment_ids">${e.shipments.map(x => `<option value="${esc(x.shipment_id)}" ${(p.shipment_ids || []).includes(x.shipment_id) ? 'selected' : ''}>${esc(x.label)}</option>`).join('')}</select><label class="f">Delay (days)</label>${num('delay_days', 1, 120)}`);
  }
  return `<label class="f">Inventory position</label><select data-field="position"><option value="">Select…</option>${e.positions.map(x => `<option value="${x.factory_id}|${x.component_id}" ${p.factory_id === x.factory_id && p.component_id === x.component_id ? 'selected' : ''}>${esc(x.label)}</option>`).join('')}</select>
    <label class="f">Stock lost or unusable (%)</label>${num('stock_loss_pct', 0, 100)}<label class="f">Demand multiplier ${tipEl('1.0 = normal. 2.0 = consumption doubles for the duration below.')}</label>${num('demand_multiplier', 0.1, 5, 0.1)}<label class="f">Surge duration (days)</label>${num('duration_days', 1, 60)}`;
}
const defaults = sc => ({supplier_failure: {outage_days: 21, cancel_open_shipments: false}, shipment_disruption: {delay_days: 7, closure_days: 7, shipment_ids: []}, inventory_shortage: {stock_loss_pct: 0, demand_multiplier: 1.5, duration_days: 14}}[sc]);
function viewSim() {
  if (!S.ents) return loading('Loading entities from the active dataset…');
  const s = S.sim;
  const form = `<div class="card"><h3>1 · Choose a scenario</h3>${Object.entries(SCEN).map(([k, v]) => `<div class="sc ${s.scenario === k ? 'on' : ''}" data-act="scenario" data-v="${k}">${icon(v.ic)}<div><b>${v.name}</b><span>${v.desc}</span></div></div>`).join('')}
    <h3 class="mt">2 · Set the parameters</h3>${paramForm()}
    <label class="f">Budget limit for recovery actions (₹) ${tipEl('Options whose action cost exceeds this are shown but excluded from the recommendation.')}</label><input type="number" data-field="budget" min="0" step="10000" value="${s.budget}">
    ${s.error ? `<div class="alert err mt"><b>${esc(s.error.message)}</b>${s.error.details?.length ? '<ul>' + s.error.details.map(x => `<li>${esc(x)}</li>`).join('') + '</ul>' : ''}${s.error.hint ? '<div style="margin-top:6px">' + esc(s.error.hint) + '</div>' : ''}</div>` : ''}
    <div class="row mt"><button class="btn pri" data-act="run" ${s.running ? 'disabled' : ''}>${s.running ? '<span class="spin"></span> Simulating…' : '▶ Run simulation'}</button></div>
    ${S.dash?.disruptions?.some(x => x.simulate) ? `<p class="hint mt">Or replay a recorded event: ${S.dash.disruptions.filter(x => x.simulate).map(x => `<a href="#" data-act="load-disruption" data-id="${esc(x.disruption_id)}" style="color:var(--blue)">${esc(x.event_type.replace('_', ' ').toLowerCase())} · ${esc(x.entity_id)}</a>`).join(', ')}</p>` : ''}</div>`;
  return `<h2 class="title">Simulator & Recovery Plans</h2><p class="sub">Break the network on purpose: the engine propagates the event from supplier to shipment to inventory to production line, then compares recovery options against a no-action baseline.</p>
  <div class="grid sim"><div>${form}</div><div id="sim-out">${s.result ? simResult() : `<div class="card"><div class="empty">${icon('flask').replace('<svg', '<svg style="width:34px;height:34px;margin:0 auto 10px;stroke:var(--faint);fill:none;stroke-width:1.5"')}Pick a scenario on the left and run it. Results, evidence and recovery options appear here.</div></div>`}</div></div>`;
}
function stockChart(p, rec) {
  const W = 700, H = 230, L = 46, B = 28, T = 12, R = 12, n = 45;
  const series = [['No disruption', p.series_baseline, '#5d6c8a', '5 4'], ['No action', rec.options[0].series, '#ef5b5b', ''], ...(rec.recommended_id && rec.recommended_id !== 'NO_ACTION' ? [['Recommended', rec.options.find(o => o.option_id === rec.recommended_id).series, '#38e0c8', '']] : [])];
  const max = Math.max(1, ...series.flatMap(s => s[1]));
  const x = i => L + (W - L - R) * i / (n - 1), y = v => T + (H - T - B) * (1 - v / max);
  const grid = [0, .25, .5, .75, 1].map(f => `<line x1="${L}" x2="${W - R}" y1="${y(max * f)}" y2="${y(max * f)}" stroke="#1a2540"/><text x="${L - 8}" y="${y(max * f) + 4}" text-anchor="end" fill="#5d6c8a" font-size="10" font-family="IBM Plex Mono">${nf.format(max * f)}</text>`).join('');
  const xs = [0, 15, 30, 44].map(i => `<text x="${x(i)}" y="${H - 8}" text-anchor="middle" fill="#5d6c8a" font-size="10" font-family="IBM Plex Mono">${i === 0 ? 'today' : '+' + i + 'd'}</text>`).join('');
  const lines = series.map(([, s, c, da]) => `<polyline fill="none" stroke="${c}" stroke-width="2.2" ${da ? `stroke-dasharray="${da}"` : ''} points="${s.map((v, i) => x(i) + ',' + y(v)).join(' ')}"/>`).join('');
  return `<svg viewBox="0 0 ${W} ${H}" width="100%" role="img" aria-label="Projected stock level">${grid}${xs}${lines}</svg><div class="legend">${series.map(s => `<span><i style="background:${s[2]}"></i>${s[0]}</span>`).join('')}<span>units on hand at end of day</span></div>`;
}
function lanes(res, p, rec) {
  const drv = res.drivers.filter(x => x.factory_id === p.factory_id && x.component_id === p.component_id);
  const sup = [...new Set(drv.map(x => x.supplier_id).filter(Boolean))], shp = drv.filter(x => x.shipment_id);
  const best = rec.options.find(o => o.option_id === rec.recommended_id), base = rec.options[0];
  const lineTxt = p.lines.length ? p.lines.map(l => l.name).join(', ') : 'no line mapped';
  const so = p.disrupted.stockout_in_days;
  const l1 = `<div class="lane"><div class="lb">NO ACTION</div><div class="node down">${sup.length ? esc(sup.join(', ')) : 'Demand / stock shock'}<small>${esc(res.scenario.replace('_', ' '))}</small></div><div class="arrow">→</div>
    <div class="node down">${shp.length ? shp.length + ' shipment(s)' : 'No inbound change'}<small>${shp[0] ? 'ETA ' + esc(shp[0].old_eta || '—') + ' → ' + esc(shp[0].new_eta || 'cancelled') : '—'}</small></div><div class="arrow">→</div>
    <div class="node down">${esc(p.component)} @ ${esc(p.factory)}<small>stockout in ${dd(so)} d · ${dd(base.stockout_days)} d short</small></div><div class="arrow">→</div><div class="node down">${esc(lineTxt)}<small>${p.production_loss_cost == null ? 'impact not estimated' : 'est. margin lost ' + inr(base.production_loss_cost)}</small></div></div>`;
  const l2 = best && best.type !== 'NO_ACTION' ? `<div class="lane"><div class="lb">RECOMMENDED</div><div class="node up">${esc(OPT_TYPE[best.type])}<small>${esc(best.label.replace(/^[A-Za-z]+ /, '').slice(0, 42))}</small></div><div class="arrow">→</div>
    <div class="node up">Supply added<small>action cost ${inr(best.action_cost)}</small></div><div class="arrow">→</div><div class="node ${best.stockout_days > .05 ? 'warn' : 'up'}">${esc(p.component)} @ ${esc(p.factory)}<small>${best.stockout_days > .05 ? dd(best.stockout_days) + ' d short remain' : 'no stockout projected'}</small></div><div class="arrow">→</div>
    <div class="node ${best.stockout_days > .05 ? 'warn' : 'up'}">${esc(lineTxt)}<small>est. margin lost ${inr(best.production_loss_cost)}</small></div></div>` : '';
  return l1 + l2;
}
function optionsTable(rec) {
  const base = rec.options[0];
  return `<div class="tw"><table><thead><tr><th>Option</th><th class="r">Action cost</th><th class="r">Est. production loss</th><th class="r">Est. total</th><th class="r">vs baseline</th><th class="r">Recovery</th><th class="r">Stockout</th><th class="r">Op. risk ${tipEl('0-100 assumption-based: base value per option type, blended with supplier risk or donor impact.')}</th><th class="r">Score ${tipEl('0-100. Min-max normalised cost, recovery time, production loss, unmet-demand share and operational risk with fixed documented weights. Higher is better; only comparable within this table.')}</th><th>Approval</th></tr></thead><tbody>
  ${rec.options.map(o => { const isRec = o.option_id === rec.recommended_id, off = !o.feasible || !o.within_budget;
    if (!o.feasible) return `<tr class="off"><td><b>${esc(o.label)}</b><div class="hint">${esc(o.reason)}</div></td><td colspan="9"></td></tr>`;
    return `<tr class="${isRec ? 'rec' : o.type === 'NO_ACTION' ? 'base' : off ? 'off' : ''}"><td><span class="tag t-${o.type === 'NO_ACTION' ? 'red' : 'blue'}">${OPT_TYPE[o.type]}</span> ${isRec ? '<span class="tag t-teal">recommended</span>' : ''}<div style="margin-top:5px"><b>${esc(o.label)}</b></div>${o.reason ? `<div class="hint c-amber">${esc(o.reason)}</div>` : ''}</td>
      <td class="r num">${inr(o.action_cost)}</td><td class="r num">${o.production_loss_cost == null ? 'n/a' : inr(o.production_loss_cost)}</td><td class="r num"><b>${inr(o.total_cost)}</b></td>
      <td class="r num ${o.type === 'NO_ACTION' ? 'c-dim' : o.delta_total_cost <= 0 ? 'c-teal' : 'c-red'}">${o.type === 'NO_ACTION' ? '—' : (o.delta_total_cost <= 0 ? '−' : '+') + inr(Math.abs(o.delta_total_cost))}</td>
      <td class="r num">${o.recovered ? o.recovery_days + ' d' : '>' + o.recovery_days + ' d'}${o.type !== 'NO_ACTION' ? `<div class="hint">${sgn(o.delta_recovery_days, 0, ' d')}</div>` : ''}</td>
      <td class="r num">${dd(o.stockout_days)} d${o.type !== 'NO_ACTION' ? `<div class="hint">${sgn(o.delta_stockout_days, 1, ' d')}</div>` : ''}</td><td class="r num">${dd(o.operational_risk, 0)}</td><td class="r num"><b>${o.score == null ? '—' : o.score}</b></td>
      <td>${o.approval.required ? '<span class="tag t-amber">human approval</span>' : '<span class="tag t-dim">planner review</span>'}</td></tr>`; }).join('')}</tbody></table></div>
  <p class="hint">“vs baseline” is the <b>estimated difference</b> in total cost against taking no action — not realised savings. Recovery = days until demand is fully served again.</p>`;
}
function evidence(res, p, rec) {
  const best = rec.options.find(o => o.option_id === rec.recommended_id), base = rec.options[0];
  const drv = res.drivers.filter(x => x.factory_id === p.factory_id && x.component_id === p.component_id);
  const changed = drv.filter(x => x.shipment_id && x.old_eta !== x.new_eta);
  return `<dl class="ev"><dt>What happened</dt><dd>${esc(SCEN[res.scenario].name)} — ${esc(Object.entries(res.params).filter(([, v]) => v !== null && v !== false && !(Array.isArray(v) && !v.length)).map(([k, v]) => k.replace(/_/g, ' ') + ': ' + v).join(', '))}.</dd>
  <dt>Affected</dt><dd>${esc(p.component)} at ${esc(p.factory)}: ${nf.format(p.usable_stock)} pcs usable, ${nf.format(p.daily_consumption)}/day (${dd(p.cover_days)} d cover); lines: ${esc(p.lines.map(l => l.name).join(', ') || 'none mapped')}.</dd>
  <dt>Records that drove it</dt><dd>${changed.length ? changed.map(x => `${esc(x.shipment_id)} (${nf.format(x.qty)} pcs, ${esc(x.old_eta)} → ${esc(x.new_eta || 'cancelled')}: ${esc(x.effect)})`).join('; ') : drv.map(x => esc(x.effect)).join('; ') || '—'}</dd>
  <dt>Fields &amp; assumptions</dt><dd>inventory.on_hand_qty, daily_consumption · shipments.estimated_arrival, status, route · supplier_components price / lead time / capacity · production_lines output &amp; margin · delivery_history. Assumptions in the panel below.</dd>
  <dt>Alternatives considered</dt><dd>${rec.options.filter(o => o.type !== 'NO_ACTION').map(o => esc(o.label) + (o.feasible ? '' : ' (not feasible)')).join('; ') || 'none'}${rec.excluded.length ? '. Not evaluated: ' + rec.excluded.map(x => esc(x.reason)).join(' ') : ''}</dd>
  <dt>Versus baseline</dt><dd>${best && best.type !== 'NO_ACTION' ? `Estimated difference: total cost ${best.delta_total_cost <= 0 ? '−' : '+'}${inr(Math.abs(best.delta_total_cost))}, stockout ${sgn(best.delta_stockout_days, 1, ' d')}, recovery ${sgn(best.delta_recovery_days, 0, ' d')} (baseline: ${dd(base.stockout_days)} d stockout, ${inr(base.total_cost)} est. total).` : 'No intervention beats the baseline.'}</dd>
  <dt>Still uncertain</dt><dd><ul class="ul" style="margin:0">${rec.uncertainty.map(u => `<li>${esc(u)}</li>`).join('')}</ul></dd></dl>`;
}
function simResult() {
  const s = S.sim, res = s.result, ps = res.pairs.filter(x => x.recovery);
  const sm = res.summary, mode = res.mode;
  let out = `<div class="row"><span class="pill ${mode === 'demo' ? 'demo' : 'live'}"><span class="dot"></span><b>${mode === 'demo' ? 'SYNTHETIC DEMO' : 'Exasol data'}</b></span><span class="hint mono">${esc(res.run_id)} · ${res.persisted === 'exasol' ? 'saved to Exasol (SCENARIO_RUNS, RECOVERY_OPTIONS)' : res.persisted === 'memory' ? 'kept in memory only (demo)' : 'not saved'}</span></div>`;
  if (res.persist_error) out += `<div class="alert warn mt">The simulation ran, but saving it to Exasol failed: ${esc(res.persist_error)}</div>`;
  if (!ps.length) return out + `<div class="card mt"><h3>No stockout projected</h3><p class="sub" style="margin:8px 0 0">${sm.pairs_affected ? 'The affected positions have enough buffer and recorded inbound supply to avoid a stockout inside the 45-day window. No recovery action is needed.' : 'This scenario did not change any inventory position (for example, no inbound shipment matched). Check the selection.'}</p>${res.drivers.length ? `<details open><summary>What the model changed</summary><ul class="ul">${res.drivers.map(x => `<li>${esc(x.shipment_id || x.factory_id)}: ${esc(x.effect)}</li>`).join('')}</ul></details>` : ''}</div>`;
  out += `<div class="grid k4 mt" style="grid-template-columns:repeat(4,1fr)"><div class="card kpi red"><div class="lbl">At risk</div><div class="num c-red">${sm.pairs_at_risk}</div><div class="foot">positions</div></div>
    <div class="card kpi amber"><div class="lbl">First stockout</div><div class="num c-amber">${dd(sm.earliest_stockout_days)} d</div><div class="foot">no action</div></div>
    <div class="card kpi"><div class="lbl">Est. cost, no action</div><div class="num" style="font-size:22px">${inr(sm.no_action_cost)}</div><div class="foot">margin-based estimate</div></div>
    <div class="card kpi"><div class="lbl">Recovery</div><div class="num">${sm.max_recovery_days}<span class="c-dim" style="font-size:16px"> d</span></div><div class="foot">if no action</div></div></div>`;
  if (s.pair >= ps.length) s.pair = 0;
  const p = ps[s.pair], rec = p.recovery, best = rec.options.find(o => o.option_id === rec.recommended_id);
  out += `<div class="tabs">${ps.map((x, i) => `<button class="tabbtn ${i === s.pair ? 'on' : ''}" data-act="pair" data-i="${i}">${esc(x.component)} · ${esc(x.factory)}</button>`).join('')}</div>
  <div class="card"><h3>Cascade — ${esc(p.component)} at ${esc(p.factory)} ${tipEl('Supplier → shipments → inventory position → production lines, with and without the recommended action.')}</h3>${lanes(res, p, rec)}</div>
  <div class="card mt"><h3>Projected stock level</h3><p class="hint">Day-by-day projection: usable stock + recorded inbound − consumption.</p>${stockChart(p, rec)}</div>
  <div class="card mt"><h3>Recovery plan comparison</h3><p class="hint">Baseline first. Costs are estimates built from the assumptions below.</p>${optionsTable(rec)}${rec.excluded.length ? `<details><summary>Options not evaluated (${rec.excluded.length})</summary><ul class="ul">${rec.excluded.map(x => `<li><b>${esc(OPT_TYPE[x.type] || x.type)}</b>: ${esc(x.reason)}</li>`).join('')}</ul></details>` : ''}</div>`;
  out += `<div class="card mt" style="border-color:${best && best.type !== 'NO_ACTION' ? '#1f6f66' : 'var(--line)'}"><h3>${best ? (best.type === 'NO_ACTION' ? 'Recommendation: no action' : 'Recommended: ' + esc(best.label)) : 'No confident recommendation'}</h3><p style="font-size:14px;color:var(--dim);margin:6px 0 14px">${esc(rec.message)}</p>${evidence(res, p, rec)}`;
  if (best) {
    const d = s.decision;
    out += `<div class="alert ${best.approval.required ? 'warn' : 'info'} mt"><b>${best.approval.required ? 'Human approval required.' : 'Planner review.'}</b> ${esc(best.approval.reason)} SupplyShield only recommends: no order is placed and no external system is changed. The decision below is recorded for the audit trail.</div>
    ${d ? `<div class="alert info mt">Decision recorded: <b>${esc(d.decision)}</b> for ${esc(d.option_id)} (${esc(d.stored_in)}).</div>` : `<label class="f">Decision note (optional)</label><input type="text" id="dec-note" maxlength="300" placeholder="e.g. waiting for quote from buyer">
    <div class="row mt"><button class="btn ok" data-act="decide" data-d="APPROVED" data-o="${esc(best.option_id)}">Record: approve</button><button class="btn bad" data-act="decide" data-d="REJECTED" data-o="${esc(best.option_id)}">Record: reject</button><button class="btn out" data-act="decide" data-d="DEFERRED" data-o="${esc(best.option_id)}">Defer</button></div>`}`;
  }
  out += `<details><summary>Calculation details &amp; assumptions</summary><table><tbody>
    <tr><td>Inventory cover</td><td class="mono">usable stock ÷ daily consumption = ${nf.format(p.usable_stock)} ÷ ${nf.format(p.daily_consumption)} = ${dd(p.cover_days, 2)} d</td></tr>
    <tr><td>Stockout (no action)</td><td class="mono">first day stock + arrivals &lt; demand: ${dd(p.disrupted.stockout_in_days, 2)} d; unmet ${nf.format(p.disrupted.unmet_units)} pcs (${dd(p.disrupted.unmet_share * 100)}% of window demand)</td></tr>
    <tr><td>Recorded inbound after event</td><td class="mono">${p.arrivals.map(a => esc(a.shipment_id) + ': ' + nf.format(a.qty) + ' pcs @ day ' + a.eta).join('; ') || 'none'}</td></tr>
    <tr><td>Production loss</td><td class="mono">${p.lines.map(l => `${esc(l.name)}: ${nf.format(l.daily_output_units)}/day × ₹${nf.format(l.margin_per_unit)} × ${dd(p.disrupted.stockout_days, 2)} d`).join('; ') || 'no line mapped'}</td></tr>
    <tr><td>Score</td><td class="mono">100 × (1 − Σ weight × normalised penalty); weights ${esc(Object.entries(res.assumptions.score_weights).map(([k, v]) => k + ' ' + v).join(', '))}</td></tr>
    ${rec.options.filter(o => o.feasible && o.type !== 'NO_ACTION').map(o => `<tr><td>${esc(o.option_id)}</td><td class="hint">${esc(o.notes)}${o.stress_delay_days ? ' Stress test (+' + o.stress_delay_days + ' d late): ' + dd(o.stress_stockout_days) + ' d stockout.' : ''}</td></tr>`).join('')}</tbody></table>${assumptionsTable(res.assumptions)}</details></div>`;
  return out;
}

/* ---------- Decision log ---------- */
function viewLog() {
  if (!S.runs) return loading('Reading simulation history…');
  return `<h2 class="title">Decision Log</h2><p class="sub">Every simulation run with the human decision recorded for it. Recording a decision does not execute anything.</p>
  <div class="card">${S.runs.length ? `<div class="tw"><table><thead><tr><th>Run</th><th>Scenario</th><th>Decision</th><th>Option</th><th>Note</th><th>Store</th></tr></thead><tbody>${S.runs.map(r => `<tr><td class="num">${esc(r.run_id)}<div class="hint">${esc(r.created_at)}</div></td><td>${esc(r.scenario_type.replace('_', ' '))}<div class="hint">${esc(JSON.stringify(r.params || {}).replace(/[{}"]/g, ''))}</div></td>
    <td><span class="tag t-${r.decision === 'APPROVED' ? 'teal' : r.decision === 'REJECTED' ? 'red' : 'dim'}">${esc(r.decision || 'PENDING')}</span><div class="hint">${esc(r.decided_at || '')}</div></td><td class="num">${esc(r.selected_option || '—')}</td><td>${esc(r.note || '')}</td><td><span class="tag t-${r.mode === 'demo' ? 'amber' : 'teal'}">${r.mode === 'demo' ? 'demo · memory' : 'Exasol'}</span></td></tr>`).join('')}</tbody></table></div>` : '<div class="empty">No simulations yet. Run one in the Simulator.</div>'}</div>`;
}

/* ---------- Data source ---------- */
function viewSource() {
  const st = S.status; if (!st) return loading('…');
  const c = st.connection, s = st.settings;
  const stateTag = {connected: ['teal', 'connected'], error: ['red', 'error'], not_configured: ['dim', 'not configured'], unknown: ['dim', 'untested']}[c.state] || ['dim', c.state];
  return `<h2 class="title">Data Source</h2><p class="sub">Exasol (SaaS or Personal) is the project data platform. Credentials live in a local <code>.env</code> file read by the Python backend — they are never typed into, stored in, or sent to the browser.</p>
  <div class="grid two"><div class="card"><h3>Connection</h3><div class="item"><div class="body">Status <span class="tag t-${stateTag[0]}">${stateTag[1]}</span><div class="hint">${esc(c.message || '—')}</div><div class="meta">last successful query: ${esc(c.last_success_at || 'never')}${c.latency_ms != null ? ' · ' + c.latency_ms + ' ms' : ''}</div></div></div>
    <table><tbody>${[['EXASOL_DSN', s.dsn || null], ['EXASOL_USER', s.user || null], ['EXASOL_PASSWORD', s.password_set ? '•••••• (set)' : null]].map(([k, v]) => `<tr><td class="mono">${k}</td><td>${v ? esc(v) : '<span class="tag t-red">missing</span>'}</td></tr>`).join('')}<tr><td class="mono">EXASOL_SCHEMA</td><td>${esc(s.schema)}</td></tr><tr><td class="mono">EXASOL_VALIDATE_CERT</td><td>${s.validate_cert}</td></tr></tbody></table>
    <div class="row mt"><button class="btn pri" data-act="test">Test connection (SELECT 1)</button><button class="btn out" data-act="use-exasol" ${c.state === 'connected' ? '' : 'disabled'}>Use Exasol data</button><button class="btn out" data-act="demo">Use SYNTHETIC demo</button></div>
    ${S.error ? `<div class="alert err mt">${esc(S.error.message)}${S.error.hint ? '<div style="margin-top:6px">' + esc(S.error.hint) + '</div>' : ''}</div>` : ''}
    <p class="hint mt">The connection is reported as “connected” only after a real <code>SELECT 1</code> succeeds. After editing <code>.env</code>, stop and restart the app (<code>python app.py</code>), then press Test connection.</p></div>
  <div class="card"><h3>Active dataset</h3>${st.dataset ? `<table><tbody><tr><td>Mode</td><td>${st.mode === 'demo' ? '<span class="tag t-amber">SYNTHETIC DEMO (in memory)</span>' : '<span class="tag t-teal">Exasol</span>'}</td></tr><tr><td>Label</td><td>${esc(st.dataset.label)}</td></tr><tr><td>Seed / as-of</td><td class="mono">${esc(st.dataset.seed)} / ${esc(st.dataset.as_of)}</td></tr><tr><td>Last refresh</td><td class="mono">${esc(st.last_refresh_at || '—')}</td></tr></tbody></table>
    ${st.table_counts ? `<details><summary>Row counts${st.mode === 'exasol' ? ' (COUNT(*) per table in Exasol)' : ' (generated rows)'}</summary><table><tbody>${Object.entries(st.table_counts).map(([k, v]) => `<tr><td class="mono">${esc(k)}</td><td class="r num">${v}</td></tr>`).join('')}</tbody></table></details>` : ''}` : '<div class="empty">No dataset loaded.</div>'}</div></div>
  <div class="card mt"><h3>Set up Exasol (Windows)</h3><ol class="ul"><li>Copy <code>.env.example</code> to <code>.env</code> and fill in <code>EXASOL_DSN</code>, <code>EXASOL_USER</code>, <code>EXASOL_PASSWORD</code> from your running Exasol database (never invented).</li><li>Run <code>python scripts\\init_db.py</code> — creates the schema, tables and analytics views.</li><li>Run <code>python scripts\\seed_db.py</code> — loads the reproducible SYNTHETIC dataset.</li><li>Restart the app, press <b>Test connection</b>, then <b>Use Exasol data</b>.</li></ol></div>
  <div class="card mt"><h3>How Exasol is used</h3><p class="hint">Tables queried: COMPONENTS, SUPPLIERS, SUPPLIER_COMPONENTS, FACTORIES, PRODUCTION_LINES, ROUTES, INVENTORY, SHIPMENTS, DELIVERY_HISTORY, DISRUPTIONS, DATASET_META. Written: SCENARIO_RUNS, RECOVERY_OPTIONS. SQL analytics in views:</p>
  <pre>V_INVENTORY_POSITION   usable stock, cover days, below-reorder flag
V_SUPPLIER_PERFORMANCE on-time rate, average delay (from DELIVERY_HISTORY)
V_SUPPLIER_COMMITMENT  open shipments / quantity per supplier
V_INBOUND_SUPPLY       inbound quantity, next ETA, delayed quantity
V_DISRUPTION_IMPACT    shipments touched by OPEN disruptions
V_ALT_SUPPLIER_CANDIDATES  offers joined with performance
V_DASHBOARD_KPIS       open disruptions, reorder alerts, delayed shipments
V_RECOVERY_COMPARISON  saved options joined to decisions</pre>
  <pre>SELECT supplier_id, COUNT(*) AS n_deliveries,
       AVG(CASE WHEN actual_date &lt;= promised_date THEN 1 ELSE 0 END) AS on_time_rate
FROM delivery_history GROUP BY supplier_id;</pre></div>`;
}

/* ---------- render + events ---------- */
async function render() {
  renderChrome();
  const page = $('#page'); if (!S.status) return;
  let html;
  if (S.view === 'source') html = viewSource();
  else if (!hasData()) html = gate();
  else html = S.view === 'overview' ? viewOverview() : S.view === 'simulator' ? viewSim() : viewLog();
  page.innerHTML = html;
}
async function loadFor(view) {
  try {
    if (!hasData()) return render();
    if (view === 'overview' && !S.dash) { S.dash = await api('/api/dashboard'); S.status = S.dash.status; }
    if (view === 'simulator') { if (!S.ents) S.ents = await api('/api/entities'); if (!S.dash) { try { S.dash = await api('/api/dashboard'); } catch {} } }
    if (view === 'log') S.runs = await api('/api/runs');
  } catch (e) { S.error = e; S.status = S.status; }
  render();
}
async function setView(v) { S.view = v; S.error = null; render(); await loadFor(v); }
async function resetData() { S.dash = S.ents = S.runs = null; S.sim.result = null; S.sim.decision = null; }
function initParams() { S.sim.params = defaults(S.sim.scenario); S.sim.error = null; S.sim.result = null; S.sim.decision = null; S.sim.subtype = 'delay'; }
async function runSim() {
  const s = S.sim; s.running = true; s.error = null; s.decision = null; render();
  const p = {...s.params}; let scenario = s.scenario;
  if (scenario === 'shipment_disruption') { p.subtype = s.subtype; if (p.subtype === 'delay') delete p.port; }
  try { s.result = await api('/api/simulate', {scenario, params: p, budget: Number(s.budget)}); s.pair = 0; S.runs = null; }
  catch (e) { s.error = e; s.result = null; }
  s.running = false; render();
}
document.addEventListener('click', async ev => {
  const t = ev.target.closest('[data-act]'); if (!t) return; const a = t.dataset.act;
  if (t.tagName === 'A') ev.preventDefault();
  try {
    if (a === 'view') await setView(t.dataset.v);
    else if (a === 'tab') { S.tab = t.dataset.t; render(); }
    else if (a === 'scenario') { S.sim.scenario = t.dataset.v; initParams(); render(); }
    else if (a === 'subtype') { S.sim.subtype = t.dataset.v; S.sim.error = null; render(); }
    else if (a === 'pair') { S.sim.pair = +t.dataset.i; S.sim.decision = null; render(); }
    else if (a === 'run') await runSim();
    else if (a === 'demo') { S.status = await api('/api/mode', {mode: 'demo'}); resetData(); await setView(S.view === 'source' ? 'overview' : S.view); }
    else if (a === 'use-exasol') { S.error = null; S.status = await api('/api/mode', {mode: 'exasol'}); resetData(); await setView('overview'); }
    else if (a === 'test') { S.error = null; S.status = await api('/api/connection/test', {}); resetData(); render(); if (hasData()) await loadFor(S.view); }
    else if (a === 'load-disruption') {
      const ev0 = S.dash.disruptions.find(x => x.disruption_id === t.dataset.id); if (!ev0?.simulate) return;
      if (!S.ents) S.ents = await api('/api/entities');
      const sm = ev0.simulate; S.sim.scenario = sm.scenario; S.sim.params = {...defaults(sm.scenario), ...sm.params}; S.sim.subtype = sm.params.subtype || 'delay';
      S.view = 'simulator'; await runSim();
    }
    else if (a === 'decide') {
      const r = S.sim.result; S.sim.decision = await api(`/api/runs/${r.run_id}/decision`, {decision: t.dataset.d, option_id: t.dataset.o, note: ($('#dec-note') || {}).value || ''});
      S.sim.decision = {...S.sim.decision, decision: t.dataset.d, option_id: t.dataset.o}; S.runs = null; render();
    }
  } catch (e) { S.error = e; if (S.view === 'simulator') S.sim.error = e; render(); }
});
document.addEventListener('change', ev => {
  const f = ev.target.dataset.field; if (!f) return; const s = S.sim, p = s.params, el = ev.target;
  if (f === 'budget') { s.budget = el.value; return; }
  if (f === 'position') { const [fa, co] = el.value.split('|'); p.factory_id = fa || undefined; p.component_id = co || undefined; return; }
  if (f === 'shipment_ids') { p.shipment_ids = [...el.selectedOptions].map(o => o.value); return; }
  if (el.type === 'checkbox') p[f] = el.checked;
  else if (el.type === 'number') p[f] = el.value === '' ? null : Number(el.value);
  else p[f] = el.value || null;
  if (f === 'supplier_id') { p.component_id = null; render(); }
});
$('#btn-refresh').addEventListener('click', async () => {
  try { S.status = await api('/api/refresh', {}); resetData(); await loadFor(S.view); } catch (e) { S.error = e; render(); }
});
(async function boot() {
  try { S.status = await api('/api/status'); } catch (e) { $('#page').innerHTML = `<div class="alert err">${esc(e.message)}</div>`; return; }
  initParams(); await setView('overview');
})();
