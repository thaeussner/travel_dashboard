// Costs page: dashboard for everyone, entry form and entries list for the owner.
// Costs carry no assumptions (CHF, no conversion), so the page sums the rows itself. The owner sees
// their own entries immediately, including ones not yet built into the public data.
import * as store from './store.js';
import { openForm } from './editor.js';
import {
  $, chf, chf2, fmtDate, todayISO, loadJSON, initChrome, svgIn, css, showTip, hideTip, bindTip,
  makeTable, wireTableToggles, onResize, onThemeChange, toast, nf,
} from './common.js';

const FALLBACK_CATS = ['groceries', 'coffee', 'treats', 'activities', 'accommodation', 'transport', 'restaurants', 'other']
  .map(id => ({ id, label: id[0].toUpperCase() + id.slice(1) }));
const [META, BUILT] = await Promise.all([loadJSON('../data/meta.json'), loadJSON('../data/costs.json')]);
const CATS = META?.categories || BUILT?.categories || FALLBACK_CATS;
const catLabel = id => (CATS.find(c => c.id === id) || {}).label || id;
const S = { cat: 'all', period: 'all', grain: 'day' };

// ---------------------------------------------------------------- data
const isISO = s => /^\d{4}-\d{2}-\d{2}$/.test(s || '');
function normalize(r) {
  const amount = Number(String(r.amount ?? '').replace(/['’\s]/g, '').replace(',', '.'));
  if (!isISO(r.date) || !isFinite(amount) || amount === 0) return null;
  const c = r.category === 'coffe' ? 'coffee' : r.category;
  return {
    id: r.id, date: r.date, amount, country: r.country || 'Unknown', pending: !!r._pending,
    category: CATS.some(x => x.id === c) ? c : 'other',
  };
}
function allRows() {
  const src = store.isOwner() && store.hasData('costs') ? store.rows('costs') : (BUILT?.rows || []);
  return src.map(normalize).filter(Boolean)
    .sort((a, b) => a.date.localeCompare(b.date) || String(a.id).localeCompare(String(b.id)));
}

const D = s => new Date(`${s}T00:00:00Z`);
const toISO = d => d.toISOString().slice(0, 10);
const addDays = (s, n) => toISO(new Date(D(s).getTime() + n * 864e5));
const daysBetween = (a, b) => Math.round((D(b) - D(a)) / 864e5);
const weekStart = s => addDays(s, -((D(s).getUTCDay() + 6) % 7));
const maxISO = (a, b) => (a > b ? a : b);

/** The calendar days the averages are spread over (zero-spend days count too). */
function window_(rows) {
  if (!rows.length) return null;
  const today = todayISO();
  const first = rows[0].date, last = rows[rows.length - 1].date;
  const end = today >= first ? maxISO(last, today) : last;
  let start = first;
  if (S.period === '30') start = maxISO(first, addDays(end, -29));
  if (S.period === 'month') start = maxISO(first, `${end.slice(0, 7)}-01`);
  return { start, end, days: daysBetween(start, end) + 1 };
}
const PERIOD_DAYS = { day: 1, week: 7, month: 30.44 };
const keyOf = (date) => (S.grain === 'day' ? date : S.grain === 'week' ? weekStart(date) : date.slice(0, 7));
function periodKeys(w) {
  const keys = [];
  if (S.grain === 'month') {
    let [y, m] = w.start.slice(0, 7).split('-').map(Number);
    const [ey, em] = w.end.slice(0, 7).split('-').map(Number);
    while (y < ey || (y === ey && m <= em)) { keys.push(`${y}-${String(m).padStart(2, '0')}`); m++; if (m > 12) { m = 1; y++; } }
    return keys;
  }
  const step = S.grain === 'week' ? 7 : 1;
  for (let k = S.grain === 'week' ? weekStart(w.start) : w.start; k <= w.end; k = addDays(k, step)) keys.push(k);
  return keys;
}
function periodLabel(k, long = false) {
  if (S.grain === 'month') return new Date(`${k}-15T00:00:00Z`).toLocaleDateString('en-GB', { month: long ? 'long' : 'short', year: 'numeric', timeZone: 'UTC' });
  if (S.grain === 'week') return `${long ? 'Week of ' : ''}${fmtDate(k)}`;
  return fmtDate(k, long ? { weekday: 'short', day: 'numeric', month: 'short' } : undefined);
}

// ---------------------------------------------------------------- KPIs
function kpi(label, value, sub) {
  const el = document.createElement('div'); el.className = 'kpi';
  const l = document.createElement('div'); l.className = 'label'; l.textContent = label;
  const v = document.createElement('div'); v.className = 'value'; v.textContent = value;
  const s = document.createElement('div'); s.className = 'sub'; s.textContent = sub;
  el.append(l, v, s);
  return el;
}
function renderKPIs(rows, w) {
  const host = $('#kpis');
  host.replaceChildren();
  if (!w) {
    host.append(kpi('Spent', '–', 'no entries yet'), kpi('Per day', '–', ''), kpi('Per week', '–', ''), kpi('Per month', '–', ''));
    return;
  }
  const total = rows.reduce((s, r) => s + r.amount, 0);
  const perDay = total / w.days;
  const countries = new Set(rows.map(r => r.country)).size;
  const what = S.cat === 'all' ? '' : ` on ${catLabel(S.cat).toLowerCase()}`;
  host.append(
    kpi(`Spent${what}`, chf(total), `${rows.length} entries · ${countries} ${countries === 1 ? 'country' : 'countries'}`),
    kpi('Per day', chf(perDay), `over ${w.days} calendar days`),
    kpi('Per week', chf(perDay * 7), `${fmtDate(w.start)} – ${fmtDate(w.end)}`),
    kpi('Per month', chf(perDay * 30.44), 'per 30.4-day month'),
  );
}

// ---------------------------------------------------------------- charts
function emptyChart(host, text) {
  host.replaceChildren();
  const p = document.createElement('p'); p.className = 'empty'; p.textContent = text;
  host.appendChild(p);
}
function barPath(x, y, w, h, r) {
  if (h <= 0) return '';
  r = Math.min(r, w / 2, h);
  return `M${x},${y + h}V${y + r}Q${x},${y} ${x + r},${y}H${x + w - r}Q${x + w},${y} ${x + w},${y + r}V${y + h}Z`;
}

function renderTime(rows, w) {
  const host = $('#time-chart');
  if (!w || !rows.length) { emptyChart(host, 'Nothing to show for this selection yet.'); $('#time-table').replaceChildren(); return; }
  const keys = periodKeys(w);
  const tot = new Map(keys.map(k => [k, 0]));
  const byCat = new Map(keys.map(k => [k, new Map()]));
  for (const r of rows) {
    const k = keyOf(r.date);
    if (!tot.has(k)) continue;
    tot.set(k, tot.get(k) + r.amount);
    const m = byCat.get(k); m.set(r.category, (m.get(r.category) || 0) + r.amount);
  }
  const avg = rows.reduce((s, r) => s + r.amount, 0) / w.days * PERIOD_DAYS[S.grain];
  const W = Math.max(host.clientWidth, 280), H = W < 560 ? 230 : 280, m = { l: 52, r: 12, t: 16, b: 28 };
  const x = d3.scaleBand().domain(keys).range([m.l, W - m.r]).paddingInner(0.25).paddingOuter(0.1);
  const yMax = Math.max(d3.max(keys, k => tot.get(k)), avg) * 1.08 || 1;
  const y = d3.scaleLinear().domain([0, yMax]).nice().range([H - m.b, m.t]);
  const svg = svgIn(host, W, H, `Spending per ${S.grain}`);
  const ax = svg.append('g').attr('class', 'ax');
  for (const t of y.ticks(W < 560 ? 4 : 5)) {
    ax.append('line').attr('x1', m.l).attr('x2', W - m.r).attr('y1', y(t)).attr('y2', y(t));
    ax.append('text').attr('x', m.l - 8).attr('y', y(t) + 4).attr('text-anchor', 'end').text(nf.format(t));
  }
  ax.append('line').attr('class', 'base').attr('x1', m.l).attr('x2', W - m.r).attr('y1', y(0)).attr('y2', y(0));
  const every = Math.max(1, Math.ceil(keys.length / Math.max(2, Math.floor((W - m.l) / 64))));
  keys.forEach((k, i) => {
    if (i % every) return;
    ax.append('text').attr('x', x(k) + x.bandwidth() / 2).attr('y', H - 8).attr('text-anchor', 'middle').text(periodLabel(k));
  });
  const bw = Math.min(24, x.bandwidth());
  const g = svg.append('g');
  for (const k of keys) {
    const v = tot.get(k);
    const bx = x(k) + (x.bandwidth() - bw) / 2;
    g.append('path').attr('d', barPath(bx, y(v), bw, y(0) - y(v), 4)).attr('fill', css('--actual'));
  }
  svg.append('line').attr('x1', m.l).attr('x2', W - m.r).attr('y1', y(avg)).attr('y2', y(avg))
    .attr('stroke', css('--ink-2')).attr('stroke-width', 1.2);
  svg.append('text').attr('class', 'lbl halo').attr('x', m.l + 6).attr('y', y(avg) - 6)
    .text(`average ${chf(avg)} per ${S.grain}`);
  const hit = svg.append('g').selectAll('rect').data(keys).join('rect')
    .attr('x', k => x(k) - x.step() * x.paddingInner() / 2).attr('width', x.step()).attr('y', m.t).attr('height', H - m.t - m.b)
    .attr('fill', 'transparent');
  bindTip(hit, k => {
    const cats = [...byCat.get(k)].sort((a, b) => b[1] - a[1]);
    return { head: periodLabel(k, true), rows: [{ value: chf(tot.get(k), 2), label: 'total' },
      ...cats.slice(0, 5).map(([c, v]) => ({ value: chf(v, 2), label: catLabel(c) }))] };
  });
  makeTable($('#time-table'), [{ label: S.grain[0].toUpperCase() + S.grain.slice(1) }, { label: 'Total (CHF)', num: true }, { label: 'Largest category' }],
    keys.filter(k => tot.get(k)).map(k => {
      const top = [...byCat.get(k)].sort((a, b) => b[1] - a[1])[0];
      return [periodLabel(k, true), chf2(tot.get(k)), top ? `${catLabel(top[0])} (${chf2(top[1])})` : ''];
    }));
}

function hbars(host, items, { label, value, text, emphasis, tip }) {
  if (!items.length) { emptyChart(host, 'Nothing to show for this selection yet.'); return; }
  const W = Math.max(host.clientWidth, 260), rowH = 34, labelW = Math.min(130, W * 0.36), textW = W < 420 ? 96 : 150;
  const H = items.length * rowH + 4;
  const x = d3.scaleLinear().domain([0, d3.max(items, value) || 1]).range([0, Math.max(40, W - labelW - textW - 12)]);
  const svg = svgIn(host, W, H, host.getAttribute('aria-label') || '');
  items.forEach((it, i) => {
    const yc = i * rowH + rowH / 2;
    const on = !emphasis || emphasis(it);
    svg.append('text').attr('class', on ? 'lbl-strong' : 'lbl').attr('x', 0).attr('y', yc + 4).text(label(it));
    const bw = x(value(it));
    if (bw > 0) {
      svg.append('path').attr('d', `M${labelW},${yc - 9}H${labelW + bw - Math.min(4, bw)}Q${labelW + bw},${yc - 9} ${labelW + bw},${yc - 9 + Math.min(4, bw)}V${yc + 9 - Math.min(4, bw)}Q${labelW + bw},${yc + 9} ${labelW + bw - Math.min(4, bw)},${yc + 9}H${labelW}Z`)
        .attr('fill', on ? css('--actual') : css('--rule'));
    }
    svg.append('text').attr('class', 'lbl').attr('x', labelW + bw + 8).attr('y', yc + 4).text(text(it));
  });
  const hit = svg.append('g').selectAll('rect').data(items).join('rect')
    .attr('x', 0).attr('y', (d, i) => i * rowH).attr('width', W).attr('height', rowH).attr('fill', 'transparent');
  bindTip(hit, tip);
}

function renderCategories(periodRows) {
  const total = periodRows.reduce((s, r) => s + r.amount, 0);
  const by = new Map();
  for (const r of periodRows) by.set(r.category, (by.get(r.category) || 0) + r.amount);
  const items = [...by].map(([id, v]) => ({ id, v })).sort((a, b) => b.v - a.v);
  hbars($('#cat-chart'), items, {
    label: d => catLabel(d.id), value: d => d.v,
    text: d => `${chf(d.v)} · ${Math.round(d.v / total * 100)} %`,
    emphasis: S.cat === 'all' ? null : d => d.id === S.cat,
    tip: d => ({ head: catLabel(d.id), rows: [{ value: chf(d.v, 2), label: `${(d.v / total * 100).toFixed(1)} % of spending` }] }),
  });
}

function renderCountries(rows) {
  const by = new Map();
  for (const r of rows) {
    if (!by.has(r.country)) by.set(r.country, { country: r.country, total: 0, days: new Set(), first: r.date });
    const c = by.get(r.country); c.total += r.amount; c.days.add(r.date);
  }
  const items = [...by.values()].map(c => ({ ...c, nd: c.days.size, perDay: c.total / c.days.size }));
  hbars($('#country-chart'), items, {
    label: d => d.country, value: d => d.perDay,
    text: d => `${chf(d.perDay)}/day`,
    tip: d => ({ head: d.country, rows: [{ value: `${chf(d.perDay, 2)} per day`, label: `${d.nd} day${d.nd === 1 ? '' : 's'} with entries` },
      { value: chf(d.total, 2), label: 'total' }] }),
  });
}

// ---------------------------------------------------------------- owner: form and entries
function costForm(existing) {
  const rows = allRows();
  const countries = [...new Set(rows.map(r => r.country))].reverse();
  const last = rows[rows.length - 1];
  openForm({
    title: existing ? 'Edit cost' : 'Add cost',
    fields: [
      { name: 'amount', label: 'Amount (CHF)', type: 'big-number', required: true, placeholder: '0.00' },
      { name: 'date', label: 'Date', type: 'date', required: true, default: todayISO() },
      { name: 'category', label: 'Category', type: 'chips', required: true, options: CATS.map(c => ({ value: c.id, label: c.label })) },
      { name: 'country', label: 'Country', type: 'datalist', required: true, datalist: countries, default: last?.country || '' },
    ],
    values: existing ? { ...existing, amount: String(existing.amount) } : {},
    submitLabel: existing ? 'Save' : 'Add',
    validate: v => (Number(v.amount.replace(',', '.')) === 0 ? 'Amount: enter a non-zero number' : ''),
    onSave: v => {
      const amount = Number(v.amount);
      const id = existing?.id || `c${v.date.slice(2).replace(/-/g, '')}-${store.rand(3)}`;
      store.upsert('costs', { id, date: v.date, amount: amount.toFixed(2), category: v.category, country: v.country });
      toast(existing ? 'Saved' : `Added ${chf(amount, 2)}`);
    },
    onDelete: existing ? () => { store.remove('costs', existing.id); toast('Deleted'); } : undefined,
  });
}

function renderEntries(rows) {
  const host = $('#entries');
  host.replaceChildren();
  if (!rows.length) {
    const p = document.createElement('div'); p.className = 'card empty';
    const b = document.createElement('b'); b.textContent = 'No costs yet';
    p.append(b, 'Add the first one with the button above. On a phone, use the round + button.');
    host.appendChild(p);
    return;
  }
  const byDate = d3.group(rows.slice().reverse(), r => r.date);
  const box = document.createElement('div'); box.className = 'ed-group';
  let shown = 0;
  for (const [date, list] of byDate) {
    if (shown > 120 && !host.dataset.all) break;
    const day = document.createElement('div'); day.className = 'ed-day';
    const a = document.createElement('span'); a.textContent = fmtDate(date, { weekday: 'short', day: 'numeric', month: 'short', year: 'numeric' });
    const b = document.createElement('span'); b.textContent = chf(list.reduce((s, r) => s + r.amount, 0), 2);
    day.append(a, b); box.appendChild(day);
    for (const r of list) {
      const row = document.createElement('div'); row.className = `ed-row${r.pending ? ' pending' : ''}`; row.tabIndex = 0;
      row.setAttribute('role', 'button');
      const t = document.createElement('div'); t.className = 't'; t.textContent = catLabel(r.category);
      const v = document.createElement('div'); v.className = 'v'; v.textContent = chf2(r.amount);
      const d = document.createElement('div'); d.className = 'd'; d.textContent = r.country;
      row.append(t, v, d);
      const open = () => costForm(r);
      row.addEventListener('click', open);
      row.addEventListener('keydown', e => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); open(); } });
      box.appendChild(row);
      shown++;
    }
  }
  host.appendChild(box);
  if (shown < rows.length) {
    const more = document.createElement('button'); more.className = 'btn small'; more.type = 'button';
    more.textContent = `Show all ${rows.length} entries`;
    more.addEventListener('click', () => { host.dataset.all = '1'; renderEntries(rows); });
    host.appendChild(more);
  }
}

// ---------------------------------------------------------------- wiring
function render() {
  const all = allRows();
  const w = window_(all);
  const inPeriod = w ? all.filter(r => r.date >= w.start && r.date <= w.end) : [];
  const rows = S.cat === 'all' ? inPeriod : inPeriod.filter(r => r.category === S.cat);
  renderKPIs(rows, w);
  renderTime(rows, w);
  renderCategories(inPeriod);
  renderCountries(rows);
  if (store.isOwner()) renderEntries(all);
  const built = BUILT?.meta?.built;
  $('#foot').textContent = built ? `Data built ${new Date(built).toLocaleString('en-GB', { dateStyle: 'medium', timeStyle: 'short' })}` : 'No build yet';
}

const sel = $('#f-cat');
for (const o of [{ id: 'all', label: 'All categories' }, ...CATS]) {
  const op = document.createElement('option'); op.value = o.id; op.textContent = o.label; sel.appendChild(op);
}
sel.addEventListener('change', () => { S.cat = sel.value; render(); });
$('#f-period').addEventListener('change', e => { S.period = e.target.value; render(); });
document.querySelectorAll('input[name="grain"]').forEach(r => r.addEventListener('change', () => { S.grain = r.value; render(); }));
$('#add-btn').addEventListener('click', () => costForm());
$('#fab').addEventListener('click', () => costForm());
wireTableToggles();
initChrome(META);
store.onChange(render);
onResize(render);
onThemeChange(render);
render();
if (store.isOwner()) store.syncAll(['costs']);
if (location.hash === '#add' && store.isOwner()) costForm();
