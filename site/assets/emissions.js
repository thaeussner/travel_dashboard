// Emissions page: dashboard for everyone (numbers precomputed in Python), trip editor for the owner.
import * as store from './store.js';
import { openForm } from './editor.js';
import {
  $, $$, nf, sig, neg, mass, range, tonnes, kmFmt, gpkm, fmtDate, todayISO, loadJSON, initChrome,
  showTip, hideTip, bindTip, css, svgIn, logTicks, tickKg, intervalMark, makeTable, wireTableToggles,
  onResize, onThemeChange, toast,
} from './common.js';

const [META, DATA] = await Promise.all([loadJSON('../data/meta.json'), loadJSON('../data/emissions.json')]);
const DIMS = ['level', 'alloc', 'occ', 'nonco2'];
const RECOMMENDED = { level: 'destination', alloc: 'iso', occ: 'observed', nonco2: 'full', scope: 'all', ...(DATA?.defaults || {}) };
const S = { ...RECOMMENDED };
const MODE_LABEL = {
  train: 'train', bus: 'bus', coach: 'coach', ferry: 'ferry', fast_ferry: 'fast ferry', plane: 'flight',
  car: 'car', taxi: 'taxi', sail: 'sailing', bike: 'bike', walk: 'walk', other: 'other',
};
const MODES = META?.modes || Object.keys(MODE_LABEL);

const WP = new Map((DATA?.waypoints || []).map(w => [w.id, w]));
const OPT = new Map((DATA?.options || []).map(o => [o.id, o]));
const TR = new Map((DATA?.travels || []).map(t => [t.id, t]));
const wpName = id => WP.get(id)?.name || id;
const shortName = n => String(n || '').split(',')[0];

// keys into the precomputed variants
const kFull = (s = S) => `${s.alloc}|${s.occ}|${s.nonco2}`;
const kTot = (s = S) => `${s.level}|${kFull(s)}|${s.scope}`;
const tKey = t => t.dims.map(d => S[d]).join('|');
const tq = t => t.q[tKey(t)];
const inScope = d => S.scope === 'all' || !d.planned;
const journeys = () => (DATA?.journeys?.[S.level] || []).filter(inScope);
const opt = (dim, id) => DATA.lenses[dim].options.find(o => o.id === id);
const lensText = (s = S) => DIMS.map(d => opt(d, s[d]).label).join(' · ');
const legLabel = t => t.vehicle || MODE_LABEL[t.mode] || t.mode;
const placeName = p => shortName(WP.has(p) ? wpName(p) : p);
/** A row's end as shown: the airport code for flights (resolved by the build), else the place name. */
const pointOf = (r, end) => (r.mode === 'plane' && r[`${end}_code`]) || placeName(r[end]);
function optionPoints(o) {
  const rows = o.rows.map(id => TR.get(id)).filter(Boolean);
  if (!rows.length) return [];
  return [pointOf(rows[0], 'from'), ...rows.map(r => pointOf(r, 'to'))];
}
function optionSummary(o) {   // e.g. "flight via BCN"
  const rows = o.rows.map(id => TR.get(id)).filter(Boolean);
  const modes = [...new Set(rows.map(r => MODE_LABEL[r.mode] || r.mode))].join(' + ');
  const via = optionPoints(o).slice(1, -1);
  return via.length ? `${modes} via ${via.join(', ')}` : modes;
}
function optionRoute(o) {     // e.g. "ZRH via BCN to SPC"
  const p = optionPoints(o);
  if (p.length < 2) return '';
  return p.length > 2 ? `${p[0]} via ${p.slice(1, -1).join(', ')} to ${p.at(-1)}` : `${p[0]} to ${p[1]}`;
}
const optionKm = o => o.rows.reduce((s, id) => s + (TR.get(id)?.km || 0), 0);
const routeLabel = t => (t.local ? `around ${placeName(t.from)}` : `${pointOf(t, 'from')} → ${pointOf(t, 'to')}`);
function dateSpan(a, d) {    // same-day stops show one date
  if (a && d) return a === d ? fmtDate(a) : `${fmtDate(a)} – ${fmtDate(d)}`;
  return a ? `from ${fmtDate(a)}` : d ? `until ${fmtDate(d)}` : '';
}
/** Local travel at one waypoint (counted the same in both worlds), for the current lens and scope. */
function localOf(wid) {
  const e = (DATA?.local || []).find(l => l.waypoint === wid);
  const q = e?.q[`${kFull()}|${S.scope}`];
  return q && q[2] > 0 ? { q, n: e.legs.length } : null;
}

// ---------------------------------------------------------------- lens bar
function buildLensBar() {
  const row = $('#lens-row');
  for (const dim of DIMS) {
    const def = DATA.lenses[dim];
    const fs = document.createElement('fieldset'); fs.className = 'lens';
    const lg = document.createElement('legend'); lg.textContent = def.title; fs.appendChild(lg);
    const seg = document.createElement('div'); seg.className = 'seg';
    for (const o of def.options) {
      const inp = document.createElement('input');
      inp.type = 'radio'; inp.name = `lens-${dim}`; inp.id = `lens-${dim}-${o.id}`; inp.value = o.id;
      inp.addEventListener('change', () => { S[dim] = o.id; renderDash(); });
      const lab = document.createElement('label'); lab.htmlFor = inp.id; lab.textContent = o.label; lab.title = o.hint;
      seg.append(inp, lab);
    }
    fs.appendChild(seg); row.appendChild(fs);
  }
  $('#scope-all').addEventListener('change', e => { S.scope = e.target.checked ? 'all' : 'todate'; renderDash(); });
  $('#lens-reset').addEventListener('click', () => { Object.assign(S, RECOMMENDED); renderDash(); });
  $('#lens-toggle').addEventListener('click', () => {
    const open = document.body.classList.toggle('lens-open');
    $('#lens-toggle').setAttribute('aria-expanded', String(open));
  });
}
function syncInputs() {
  for (const dim of DIMS) { const el = document.getElementById(`lens-${dim}-${S[dim]}`); if (el) el.checked = true; }
  $('#scope-all').checked = S.scope === 'all';
  $('#lens-summary').textContent = lensText();
}

// ---------------------------------------------------------------- hero + robustness strip
function renderHero() {
  const t = DATA.totals[kTot()];
  const tt = v => `${tonnes(v)} t`;
  $('#hero-avoided').textContent = tonnes(t.avoided[1]);
  $('#hero-range').textContent = `${tonnes(t.avoided[0])} to ${tonnes(t.avoided[2])} t`;
  $('#hero-scope').textContent = S.scope === 'all' ? 'including planned travel' : `trip so far, to ${fmtDate(DATA.meta.today)}`;
  $('#hero-actual').textContent = tt(t.actual[1]);
  $('#hero-actual-r').textContent = `90 %: ${tonnes(t.actual[0])}–${tonnes(t.actual[2])} t`;
  $('#hero-flying').textContent = tt(t.flying[1]);
  $('#hero-flying-r').textContent = `90 %: ${tonnes(t.flying[0])}–${tonnes(t.flying[2])} t`;
  const other = DATA.totals[kTot({ ...S, scope: S.scope === 'all' ? 'todate' : 'all' })].avoided;
  const differs = Math.abs(other[1] - t.avoided[1]) > 0.5;
  $('#hero-alt').textContent = !differs ? '' : S.scope === 'all'
    ? `Trip so far: ${tonnes(other[1])} t (90 %: ${tonnes(other[0])} to ${tonnes(other[2])} t)`
    : `Including planned travel: ${tonnes(other[1])} t (90 %: ${tonnes(other[0])} to ${tonnes(other[2])} t)`;
}

function allCombos() {
  const out = [];
  for (const l of DATA.lenses.level.options) for (const a of DATA.lenses.alloc.options)
    for (const o of DATA.lenses.occ.options) for (const n of DATA.lenses.nonco2.options) {
      const s = { level: l.id, alloc: a.id, occ: o.id, nonco2: n.id, scope: S.scope };
      out.push({ s, v: DATA.totals[kTot(s)].avoided[1],
        cur: l.id === S.level && a.id === S.alloc && o.id === S.occ && n.id === S.nonco2 });
    }
  return out;
}
function renderStrip() {
  const host = $('#strip-chart');
  const combos = allCombos();
  const vals = combos.map(c => c.v);
  const pos = vals.filter(v => v > 0).length;
  const sum = $('#strip-sum');
  sum.replaceChildren();
  const b = document.createElement('b'); b.textContent = `Not flying comes out lower in ${pos} of ${combos.length}`;
  sum.append(b, ` ways of counting (from ${tonnes(d3.min(vals))} to ${tonnes(d3.max(vals))} t). Each tick is one combination of switches; the bold one is yours.`);
  const rowsDef = DATA.lenses.alloc.options;
  const W = Math.max(host.clientWidth, 260), rowH = 26, m = { l: 98, r: 14, t: 22, b: 24 };
  const H = m.t + rowsDef.length * rowH + m.b, yAx = H - m.b;
  const lo = Math.min(0, d3.min(vals)), hi = Math.max(0, d3.max(vals));
  const pad = (hi - lo) * 0.05 || 100;
  const x = d3.scaleLinear().domain([lo - pad, hi + pad]).range([m.l, W - m.r]);
  const svg = svgIn(host, W, H, `Avoided emissions under all ${combos.length} method combinations`);
  const ax = svg.append('g').attr('class', 'ax');
  ax.append('line').attr('class', 'base').attr('x1', m.l).attr('x2', W - m.r).attr('y1', yAx).attr('y2', yAx);
  for (const t of x.ticks(W < 380 ? 3 : 5)) {
    ax.append('line').attr('x1', x(t)).attr('x2', x(t)).attr('y1', m.t - 4).attr('y2', yAx);
    ax.append('text').attr('x', x(t)).attr('y', H - 6).attr('text-anchor', 'middle').text(t === 0 ? '0' : `${neg(nf.format(t / 1000))} t`);
  }
  svg.append('line').attr('x1', x(0)).attr('x2', x(0)).attr('y1', m.t - 8).attr('y2', yAx).attr('stroke', css('--ink-2')).attr('stroke-width', 1.2);
  svg.append('text').attr('class', 'lbl-muted').attr('x', x(0) - 4).attr('y', m.t - 10).attr('text-anchor', 'end').text('flying lower ←');
  svg.append('text').attr('class', 'lbl-muted').attr('x', x(0) + 4).attr('y', m.t - 10).text('→ not flying lower');
  const yRow = id => m.t + rowsDef.findIndex(r => r.id === id) * rowH + rowH / 2;
  for (const r of rowsDef) svg.append('text').attr('class', r.id === S.alloc ? 'lbl-strong' : 'lbl').attr('x', 0).attr('y', yRow(r.id) + 4).text(r.label);
  const g = svg.append('g');
  for (const c of combos.filter(c => !c.cur)) {
    const yc = yRow(c.s.alloc);
    g.append('line').attr('x1', x(c.v)).attr('x2', x(c.v)).attr('y1', yc - 7).attr('y2', yc + 7)
      .attr('stroke', css('--ink-2')).attr('stroke-opacity', 0.5).attr('stroke-width', 2).attr('stroke-linecap', 'round');
  }
  const cur = combos.find(c => c.cur), yc = yRow(cur.s.alloc);
  g.append('line').attr('x1', x(cur.v)).attr('x2', x(cur.v)).attr('y1', yc - 10).attr('y2', yc + 10)
    .attr('stroke', css('--ink')).attr('stroke-width', 3).attr('stroke-linecap', 'round');
  g.append('circle').attr('cx', x(cur.v)).attr('cy', yc - 10).attr('r', 4.5).attr('fill', css('--ink')).attr('stroke', css('--surface')).attr('stroke-width', 2);
  svg.append('rect').attr('x', m.l).attr('y', m.t - 4).attr('width', W - m.l - m.r).attr('height', yAx - m.t + 4).attr('fill', 'transparent')
    .on('pointermove', evt => {
      const [px, py] = d3.pointer(evt);
      const row = rowsDef[Math.max(0, Math.min(rowsDef.length - 1, Math.floor((py - m.t) / rowH)))].id;
      const c = combos.filter(cc => cc.s.alloc === row).reduce((a, bb) => (Math.abs(x(bb.v) - px) < Math.abs(x(a.v) - px) ? bb : a));
      showTip(evt, lensText(c.s) + (c.cur ? ' (current)' : ''), [{ value: `${tonnes(c.v)} t`, label: 'avoided (median)' }]);
    })
    .on('pointerleave', hideTip);
  makeTable($('#strip-table'), [{ label: 'Way of counting' }, { label: 'Avoided (median)', num: true }],
    combos.slice().sort((a, bb) => bb.v - a.v).map(c => [lensText(c.s) + (c.cur ? ' (current)' : ''), `${tonnes(c.v)} t`]));
}

// ---------------------------------------------------------------- route with alternative arcs
function wrapWords(text, max = 15) {
  const lines = [''];
  for (const w of String(text).split(/\s+/)) {
    const cur = lines[lines.length - 1];
    if (cur && (cur + ' ' + w).length > max) lines.push(w); else lines[lines.length - 1] = cur ? `${cur} ${w}` : w;
  }
  return lines.slice(0, 2);
}
function renderRoute() {
  const host = $('#route-chart');
  const wps = DATA.waypoints.filter(w => S.scope === 'all' || !w.planned);
  const ids = new Set(wps.map(w => w.id));
  const legs = DATA.travels.filter(t => t.type === 'leg' && !t.local && inScope(t) && ids.has(t.from) && ids.has(t.to));
  const segs = [...d3.group(legs, t => `${t.from}|${t.to}`).values()].map(list => ({
    from: list[0].from, to: list[0].to, legs: list, km: d3.sum(list, t => t.km), planned: list.every(t => t.planned),
    label: [...new Set(list.map(legLabel))].join(' · '),
  }));
  const js = journeys().filter(j => j.option && ids.has(j.start) && ids.has(j.end));
  const avail = host.parentElement.clientWidth;
  const step = Math.max(84, Math.min(130, (avail - 120) / Math.max(1, wps.length - 1)));
  const W = Math.max(avail, (wps.length - 1) * step + 120), H = 392, y0 = 252;
  const fit = (text, px, size = 6.6) => { const n = Math.max(4, Math.floor(px / size)); return text.length > n ? `${text.slice(0, n - 1)}…` : text; };
  const x = d3.scalePoint().domain(wps.map(w => w.id)).range([60, W - 60]);
  const svg = svgIn(host, W, H, 'Route with the alternatives used for the selected comparison');
  const maxKm = d3.max(DATA.options, optionKm) || 1;
  for (const sg of segs) {
    svg.append('line').attr('x1', x(sg.from)).attr('x2', x(sg.to)).attr('y1', y0).attr('y2', y0)
      .attr('stroke', css('--actual')).attr('stroke-width', 3).attr('stroke-linecap', 'round').attr('stroke-dasharray', sg.planned ? '7 6' : null);
    const mx = (x(sg.from) + x(sg.to)) / 2;
    const lab = fit(sg.label, Math.abs(x(sg.to) - x(sg.from)) - 8);
    svg.append('text').attr('class', 'lbl').attr('x', mx).attr('y', y0 + 19).attr('text-anchor', 'middle').text(lab);
    svg.append('text').attr('class', 'lbl-muted').attr('x', mx).attr('y', y0 + 33).attr('text-anchor', 'middle').text(`${kmFmt(sg.km)} km`);
    const hit = svg.append('line').attr('x1', x(sg.from)).attr('x2', x(sg.to)).attr('y1', y0).attr('y2', y0).attr('stroke', 'transparent').attr('stroke-width', 18).datum(sg);
    bindTip(hit, d => ({ head: `${shortName(wpName(d.from))} → ${shortName(wpName(d.to))}`,
      rows: d.legs.map(t => ({ value: mass(tq(t)[1]), label: `${legLabel(t)}, ${kmFmt(t.km)} km`, color: css('--actual') })) }));
  }
  for (const j of js) {
    const o = OPT.get(j.option);
    const x1 = x(j.start), x2 = x(j.end);
    const h = 44 + 150 * Math.sqrt(optionKm(o) / maxKm);
    const path = `M${x1},${y0} C${x1},${y0 - h * 1.33} ${x2},${y0 - h * 1.33} ${x2},${y0}`;
    svg.append('path').attr('d', path).attr('fill', 'none').attr('stroke', css('--flying')).attr('stroke-width', 2.2).attr('stroke-dasharray', j.planned ? '7 6' : null);
    const mx = (x1 + x2) / 2, top = y0 - h;
    const q = j.q[kFull()].flying;
    const summary = fit(optionSummary(o), Math.max(70, x2 - x1 + 30), 7);
    svg.append('text').attr('class', 'lbl-strong').attr('x', mx).attr('y', top - 22).attr('text-anchor', 'middle').text(summary);
    svg.append('text').attr('class', 'lbl').attr('x', mx).attr('y', top - 8).attr('text-anchor', 'middle').text(mass(q[1]));
    const hit = svg.append('path').attr('d', path).attr('fill', 'none').attr('stroke', 'transparent').attr('stroke-width', 16).datum(j);
    bindTip(hit, d => ({ head: `${d.title}: ${optionRoute(OPT.get(d.option))}`, rows: [
      { value: mass(d.q[kFull()].flying[1]), label: `alternative, ${range(d.q[kFull()].flying)}`, color: css('--flying') },
      { value: mass(d.q[kFull()].actual[1]), label: `travelled, ${range(d.q[kFull()].actual)}`, color: css('--actual') },
      { value: `${kmFmt(optionKm(OPT.get(d.option)))} km`, label: 'alternative distance' }] }));
  }
  for (const w of wps) {
    const dest = w.type === 'destination';
    svg.append('circle').attr('cx', x(w.id)).attr('cy', y0).attr('r', dest ? 7 : 5.5)
      .attr('fill', dest ? css('--ink') : css('--surface')).attr('stroke', dest ? css('--surface') : css('--ink-2')).attr('stroke-width', 2);
    const lines = wrapWords(shortName(w.name), Math.max(9, Math.floor(step / 7.6)));
    lines.forEach((ln, i) => svg.append('text').attr('class', 'lbl-strong').attr('x', x(w.id)).attr('y', y0 + 58 + i * 15).attr('text-anchor', 'middle').text(ln));
    const cap = dateSpan(w.arrive, w.depart);
    const yy = y0 + 58 + lines.length * 15;
    svg.append('text').attr('class', 'lbl-muted').attr('x', x(w.id)).attr('y', yy + 2).attr('text-anchor', 'middle').text(cap);
    svg.append('text').attr('class', 'lbl-muted').attr('x', x(w.id)).attr('y', yy + 16).attr('text-anchor', 'middle').text(w.planned ? `${w.type} · planned` : w.type);
    const loc = localOf(w.id);
    if (loc) {
      const t = svg.append('text').attr('class', 'lbl').attr('x', x(w.id)).attr('y', yy + 32).attr('text-anchor', 'middle').text(`+ local ${mass(loc.q[1])}`).datum(loc);
      bindTip(t, d => ({ head: `Local travel around ${shortName(w.name)}`, rows: [
        { value: mass(d.q[1]), label: `${d.n} trip${d.n === 1 ? '' : 's'}, ${range(d.q)}`, color: css('--actual') },
        { value: 'same', label: 'in both worlds: no alternative replaces it' }] }));
    }
  }
  $('#level-explain').textContent = opt('level', S.level).explain;
}

// ---------------------------------------------------------------- cumulative
function renderCumulative() {
  const host = $('#cum-chart');
  const today = DATA.meta.today;
  const pts = DATA.cumulative[`${S.level}|${kFull()}`].filter(p => S.scope === 'all' || p.date <= today);
  if (pts.length < 2) { host.replaceChildren(); $('#cum-table').replaceChildren(); return; }
  const W = Math.max(host.clientWidth, 280), narrow = W < 560;
  const H = narrow ? 270 : 330, m = { l: 44, r: narrow ? 14 : 112, t: 34, b: 28 };
  const parse = d3.utcParse('%Y-%m-%d');
  const X = pts.map(p => parse(p.date));
  const x = d3.scaleUtc().domain(d3.extent(X)).range([m.l, W - m.r]);
  const yMax = d3.max(pts, p => Math.max(p.flying[2], p.actual[2])) * 1.06 || 1;
  const y = d3.scaleLinear().domain([0, yMax]).nice().range([H - m.b, m.t]);
  const svg = svgIn(host, W, H, 'Cumulative emissions, actual travel vs with alternatives');
  const ax = svg.append('g').attr('class', 'ax');
  for (const t of y.ticks(narrow ? 4 : 5)) {
    ax.append('line').attr('x1', m.l).attr('x2', W - m.r).attr('y1', y(t)).attr('y2', y(t));
    ax.append('text').attr('x', m.l - 8).attr('y', y(t) + 4).attr('text-anchor', 'end').text(t === 0 ? '0' : t >= 1000 ? `${nf.format(t / 1000)} t` : `${nf.format(t)} kg`);
  }
  ax.append('line').attr('class', 'base').attr('x1', m.l).attr('x2', W - m.r).attr('y1', y(0)).attr('y2', y(0));
  let lastTick = -Infinity;
  for (const t of x.ticks(narrow ? 4 : 7)) {
    if (x(t) - lastTick < 58) continue;
    ax.append('text').attr('x', x(t)).attr('y', H - 8).attr('text-anchor', 'middle').text(d3.utcFormat('%-d %b')(t));
    lastTick = x(t);
  }
  const iToday = pts.findIndex(p => p.date === today);
  for (const [key, col, wash] of [['flying', css('--flying'), css('--flying-wash')], ['actual', css('--actual'), css('--actual-wash')]]) {
    svg.append('path').attr('d', d3.area().curve(d3.curveStepAfter).x((p, i) => x(X[i])).y0(p => y(p[key][0])).y1(p => y(p[key][2]))(pts)).attr('fill', wash);
    const line = idx => d3.line().curve(d3.curveStepAfter).x(i => x(X[i])).y(i => y(pts[i][key][1]))(idx);
    const idx = pts.map((p, i) => i);
    const cut = iToday === -1 ? idx.length - 1 : iToday;
    svg.append('path').attr('d', line(idx.slice(0, cut + 1))).attr('fill', 'none').attr('stroke', col).attr('stroke-width', 2.2);
    if (cut < idx.length - 1) svg.append('path').attr('d', line(idx.slice(cut))).attr('fill', 'none').attr('stroke', col).attr('stroke-width', 2.2).attr('stroke-dasharray', '6 5');
    if (!narrow) {
      const last = pts[pts.length - 1][key];
      svg.append('text').attr('class', 'lbl-strong').attr('x', W - m.r + 8).attr('y', y(last[1]) + 4).text(`${key === 'flying' ? 'Alternatives' : 'Actual'} ${mass(last[1])}`);
    }
  }
  let lastRight = -Infinity;
  for (const w of DATA.waypoints.filter(w => w.type === 'destination' && w.arrive && (S.scope === 'all' || w.arrive <= today))) {
    if (w.arrive < pts[0].date) continue;
    const mx = x(parse(w.arrive));
    svg.append('line').attr('x1', mx).attr('x2', mx).attr('y1', m.t - 6).attr('y2', m.t + 2).attr('stroke', css('--ink-2'));
    let nm = shortName(w.name);
    if (nm.length > 16) nm = `${nm.slice(0, 15)}…`;
    const half = nm.length * 3.1;   // ~6.2 px per character at 11.5 px
    if (mx - half < lastRight + 6) continue;   // ticks always, labels only where they fit
    svg.append('text').attr('class', 'lbl-muted').attr('x', mx).attr('y', m.t - 10).attr('text-anchor', 'middle').text(nm);
    lastRight = mx + half;
  }
  if (S.scope === 'all' && iToday > 0 && iToday < pts.length - 1) {
    const tx = x(parse(today));
    svg.append('line').attr('x1', tx).attr('x2', tx).attr('y1', m.t).attr('y2', H - m.b).attr('stroke', css('--rule'));
    svg.append('text').attr('class', 'lbl-muted').attr('x', tx + 4).attr('y', H - m.b - 6).text('today');
  }
  const cross = svg.append('line').attr('y1', m.t).attr('y2', H - m.b).attr('stroke', css('--ink-2')).attr('visibility', 'hidden');
  svg.append('rect').attr('x', m.l).attr('y', m.t).attr('width', W - m.l - m.r).attr('height', H - m.t - m.b).attr('fill', 'transparent')
    .on('pointermove', evt => {
      const d = x.invert(d3.pointer(evt)[0]);
      const i = Math.max(0, d3.bisectRight(X, d) - 1);
      const p = pts[i];
      cross.attr('x1', x(d)).attr('x2', x(d)).attr('visibility', 'visible');
      showTip(evt, `${d3.utcFormat('%-d %b %Y')(d)}${p.date > today ? ' · planned' : ''}`, [
        { value: mass(p.flying[1]), label: `with alternatives, ${range(p.flying)}`, color: css('--flying') },
        { value: mass(p.actual[1]), label: `actual, ${range(p.actual)}`, color: css('--actual') },
        { value: mass(p.avoided[1]), label: `avoided, ${range(p.avoided)}` }]);
    })
    .on('pointerleave', () => { cross.attr('visibility', 'hidden'); hideTip(); });
  makeTable($('#cum-table'), [{ label: 'Date' }, { label: 'Actual (median)', num: true }, { label: 'With alternatives (median)', num: true }, { label: 'Avoided, 90 %', num: true }],
    pts.map(p => [fmtDate(p.date) + (p.date > today ? ' (planned)' : ''), mass(p.actual[1]), mass(p.flying[1]), range(p.avoided)]));
}

// ---------------------------------------------------------------- journeys
function renderJourneys() {
  const host = $('#jr-chart');
  const js = journeys();
  if (!js.length) { host.replaceChildren(); $('#jr-table').replaceChildren(); return; }
  const W = Math.max(host.clientWidth, 280), narrow = W < 640;
  const labelW = narrow ? 0 : Math.min(290, W * 0.34), rightW = narrow ? 12 : 128;
  const rowH = narrow ? 84 : 60, top = 8, axisH = 26;
  const k = kFull();
  const localQ = DATA.local_total?.[`${k}|${S.scope}`];
  const hasLocal = !!localQ && localQ[2] > 0;
  const nLocal = (DATA.local || []).reduce((n, l) => n + l.legs.filter(id => inScope(TR.get(id))).length, 0);
  const H = top + (js.length + (hasLocal ? 1 : 0)) * rowH + axisH;
  const vals = js.flatMap(j => [j.q[k].actual[0], j.q[k].actual[2],
    ...(j.option ? [j.q[k].flying[0], j.q[k].flying[2]] : []), ...j.extras.map(id => OPT.get(id).q[k][1])])
    .concat(hasLocal ? [localQ[0], localQ[2]] : []).filter(v => v > 0);
  const x = d3.scaleLog().domain([Math.max(0.5, d3.min(vals) * 0.6), (d3.max(vals) || 10) * 1.5]).range([labelW + 10, W - rightW]);
  const svg = svgIn(host, W, H, 'Actual vs alternative emissions for each journey');
  const ax = svg.append('g').attr('class', 'ax');
  for (const t of logTicks(x.domain())) {
    ax.append('line').attr('x1', x(t)).attr('x2', x(t)).attr('y1', top).attr('y2', H - axisH);
    ax.append('text').attr('x', x(t)).attr('y', H - 8).attr('text-anchor', 'middle').text(tickKg(t));
  }
  js.forEach((j, i) => {
    const yT = top + i * rowH, yMid = narrow ? yT + 52 : yT + rowH / 2;
    const g = svg.append('g');
    const o = j.option ? OPT.get(j.option) : null;
    const sub = `${j.legs.length} leg${j.legs.length === 1 ? '' : 's'}${o ? ` vs. ${optionSummary(o)}` : ' · no alternative entered'}`;
    const ty = narrow ? yT + 16 : yMid - 3;
    g.append('text').attr('class', 'lbl-strong').attr('x', 0).attr('y', ty).text(`${shortName(wpName(j.start))} → ${shortName(wpName(j.end))}${j.planned ? ' (planned)' : ''}`);
    g.append('text').attr('class', 'lbl-muted').attr('x', 0).attr('y', ty + 16).text(sub.length > 52 ? `${sub.slice(0, 51)}…` : sub);
    const qa = j.q[k].actual, qf = j.q[k].flying, qd = j.q[k].diff;
    if (o) {
      g.append('line').attr('x1', x(Math.max(qa[1], 0.5))).attr('x2', x(Math.max(qf[1], 0.5))).attr('y1', yMid).attr('y2', yMid).attr('stroke', css('--rule')).attr('stroke-width', 1.5);
      intervalMark(g, x, yMid - 6, qf.map(v => Math.max(v, 0.5)), css('--flying'));
    }
    for (const id of j.extras) {
      const eq = OPT.get(id).q[k];
      intervalMark(g, x, yMid - 6, eq.map(v => Math.max(v, 0.5)), css('--flying'), 4, true);
    }
    intervalMark(g, x, yMid + 6, qa.map(v => Math.max(v, 0.5)), css('--actual'));
    if (o) {
      const better = qd[1] >= 0;
      const ann = better ? `saves ${mass(qd[1])}` : `▲ ${mass(-qd[1])} more`;
      g.append('text').attr('class', `lbl ${better ? 'good' : 'bad'}`).attr('x', W).attr('y', narrow ? yT + 16 : yMid + 4).attr('text-anchor', 'end').text(ann);
    }
    const hit = g.append('rect').attr('x', 0).attr('y', yT).attr('width', W).attr('height', rowH).attr('fill', 'transparent').datum(j);
    bindTip(hit, d => {
      const rows = [{ value: mass(d.q[k].actual[1]), label: `travelled, ${range(d.q[k].actual)}`, color: css('--actual') }];
      if (d.option) {
        rows.unshift({ value: mass(d.q[k].flying[1]), label: `${optionSummary(OPT.get(d.option))}, ${range(d.q[k].flying)}`, color: css('--flying') });
        rows.push({ value: mass(d.q[k].diff[1]), label: `difference, ${range(d.q[k].diff)}` });
      }
      for (const id of d.extras) rows.push({ value: mass(OPT.get(id).q[k][1]), label: `other: ${optionSummary(OPT.get(id))}` });
      return { head: d.title, rows };
    });
  });
  if (hasLocal) {
    // local travel (start = end) has no alternative: it counts the same in both worlds
    const yT = top + js.length * rowH, yMid = narrow ? yT + 52 : yT + rowH / 2;
    const g = svg.append('g');
    const ty = narrow ? yT + 16 : yMid - 3;
    g.append('text').attr('class', 'lbl-strong').attr('x', 0).attr('y', ty).text('Local travel');
    g.append('text').attr('class', 'lbl-muted').attr('x', 0).attr('y', ty + 16).text(`${nLocal} trip${nLocal === 1 ? '' : 's'} · same in both worlds`);
    intervalMark(g, x, yMid + 6, localQ.map(v => Math.max(v, 0.5)), css('--actual'));
    g.append('text').attr('class', 'lbl-muted').attr('x', W).attr('y', narrow ? yT + 16 : yMid + 4).attr('text-anchor', 'end').text('no alternative');
    const hit = g.append('rect').attr('x', 0).attr('y', yT).attr('width', W).attr('height', rowH).attr('fill', 'transparent').datum(localQ);
    bindTip(hit, q => ({ head: 'Local travel around destinations', rows: [
      { value: mass(q[1]), label: `${range(q)}, counted in both worlds`, color: css('--actual') }] }));
  }
  makeTable($('#jr-table'),
    [{ label: 'Journey' }, { label: 'Travelled, 90 %', num: true }, { label: 'Main alternative, 90 %', num: true }, { label: 'Avoided (median)', num: true }],
    js.map(j => [`${j.title}${j.planned ? ' (planned)' : ''}`, range(j.q[k].actual), j.option ? range(j.q[k].flying) : '–', j.option ? mass(j.q[k].diff[1]) : '–'])
      .concat(hasLocal ? [['Local travel (no alternative)', range(localQ), '–', '0 kg']] : []));
}

// ---------------------------------------------------------------- method check
let mcSel = null;
function methodSpread(j) {
  const v = [];
  for (const a of DATA.lenses.alloc.options) for (const o of DATA.lenses.occ.options) v.push(j.q[`${a.id}|${o.id}|${S.nonco2}`].actual[1]);
  return d3.max(v) / Math.max(1, d3.min(v));
}
function renderMethodCheck() {
  const sel = $('#mc-select');
  const js = journeys().filter(j => j.option);
  const host = $('#mc-chart');
  if (!js.length) { host.replaceChildren(); $('#mc-callout').textContent = 'Enter an alternative for a journey to compare methods.'; sel.replaceChildren(); return; }
  const keyOf = j => `${j.start}|${j.end}`;
  if (!mcSel || !js.some(j => keyOf(j) === mcSel)) mcSel = keyOf(js.reduce((a, b) => (methodSpread(b) > methodSpread(a) ? b : a)));
  sel.replaceChildren();
  for (const j of js) {
    const op = document.createElement('option'); op.value = keyOf(j); op.textContent = `${shortName(wpName(j.start))} → ${shortName(wpName(j.end))}`;
    sel.appendChild(op);
  }
  sel.value = mcSel;
  const j = js.find(jj => keyOf(jj) === mcSel);
  const rows = [];
  for (const a of DATA.lenses.alloc.options) for (const o of DATA.lenses.occ.options)
    rows.push({ alloc: a, occ: o, q: j.q[`${a.id}|${o.id}|${S.nonco2}`].actual });
  const qf = j.q[kFull()].flying;
  const W = Math.max(host.clientWidth, 280), narrow = W < 520;
  const labelW = narrow ? 0 : 190, rowH = narrow ? 50 : 40, top = 34, axisH = 26;
  const H = top + rows.length * rowH + axisH;
  const vals = rows.flatMap(r => [r.q[0], r.q[2]]).concat([qf[0], qf[2]]).filter(v => v > 0);
  const x = d3.scaleLog().domain([d3.min(vals) * 0.6, d3.max(vals) * 1.5]).range([labelW + 8, W - 12]);
  const svg = svgIn(host, W, H, 'One journey under each counting method, against its alternative');
  const ax = svg.append('g').attr('class', 'ax');
  for (const t of logTicks(x.domain())) {
    ax.append('line').attr('x1', x(t)).attr('x2', x(t)).attr('y1', top - 6).attr('y2', H - axisH);
    ax.append('text').attr('x', x(t)).attr('y', H - 8).attr('text-anchor', 'middle').text(tickKg(t));
  }
  svg.append('rect').attr('x', x(qf[0])).attr('width', Math.max(2, x(qf[2]) - x(qf[0]))).attr('y', top - 6).attr('height', H - axisH - top + 6).attr('fill', css('--flying-wash'));
  svg.append('line').attr('x1', x(qf[1])).attr('x2', x(qf[1])).attr('y1', top - 6).attr('y2', H - axisH).attr('stroke', css('--flying')).attr('stroke-width', 2);
  const o = OPT.get(j.option);
  svg.append('text').attr('class', 'lbl').attr('x', x(qf[1])).attr('y', top - 12).attr('text-anchor', x(qf[1]) > W * 0.7 ? 'end' : 'middle').text(`${optionSummary(o)}: ${mass(qf[1])}`);
  let above = 0;
  rows.forEach((r, i) => {
    const yT = top + i * rowH, yMid = narrow ? yT + 34 : yT + rowH / 2;
    const cur = r.alloc.id === S.alloc && r.occ.id === S.occ;
    if (r.q[1] > qf[1]) above++;
    const label = `${r.alloc.label} · ${r.occ.label}`;
    svg.append('text').attr('class', cur ? 'lbl-strong' : 'lbl').attr('x', 0).attr('y', narrow ? yT + 14 : yMid + 4).text(label + (cur && narrow ? '  ← current' : ''));
    const g = svg.append('g');
    intervalMark(g, x, yMid, r.q.map(v => Math.max(v, x.domain()[0])), css('--actual'), cur ? 6 : 5);
    const hit = svg.append('rect').attr('x', 0).attr('y', yT).attr('width', W).attr('height', rowH).attr('fill', 'transparent').datum(r);
    bindTip(hit, d => ({ head: `${d.alloc.label} · ${d.occ.label}`, rows: [
      { value: mass(d.q[1]), label: `travelled, ${range(d.q)}`, color: css('--actual') },
      { value: mass(qf[1]), label: `alternative, ${range(qf)}`, color: css('--flying') }] }));
  });
  const same = new Set(rows.map(r => Math.round(r.q[1]))).size === 1;
  const call = $('#mc-callout');
  call.replaceChildren();
  const b = document.createElement('b');
  b.textContent = same ? 'No ferry or observed head count on this journey: every method gives the same result.' : `Above the alternative in ${above} of ${rows.length} ways of counting.`;
  call.append(b);
  makeTable($('#mc-table'), [{ label: 'Method' }, { label: 'Travelled, 90 %', num: true }, { label: 'Median', num: true }],
    rows.map(r => [`${r.alloc.label} · ${r.occ.label}`, range(r.q), mass(r.q[1])]).concat([['Alternative', range(qf), mass(qf[1])]]));
}

// ---------------------------------------------------------------- per kilometre
function renderIntensity() {
  const host = $('#int-chart');
  const items = [];
  const seen = new Set();
  for (const j of journeys()) {
    for (const id of j.legs) { const t = TR.get(id); if (t && !seen.has(id)) { items.push({ t, alt: false }); seen.add(id); } }
    if (j.option) for (const id of OPT.get(j.option).rows) { const t = TR.get(id); if (t) items.push({ t, alt: true }); }
  }
  for (const t of DATA.travels) if (t.type === 'leg' && inScope(t) && !seen.has(t.id)) items.push({ t, alt: false });
  if (!items.length) { host.replaceChildren(); return; }
  const W = Math.max(host.clientWidth, 280), narrow = W < 600;
  const labelW = narrow ? 0 : 250, rowH = narrow ? 46 : 40, top = 16, axisH = 26;
  const H = top + items.length * rowH + axisH;
  const g_ = it => tq(it.t).map(v => v / it.t.km * 1000);
  const refs = [{ label: 'car, alone', gpkm: 209 }, { label: 'car, 4 aboard', gpkm: 52 }];
  const vals = items.flatMap(it => g_(it)).concat(refs.map(r => r.gpkm)).filter(v => v > 0);
  const x = d3.scaleLog().domain([Math.max(0.3, d3.min(vals) * 0.6), d3.max(vals) * 1.4]).range([labelW + 8, W - 12]);
  const svg = svgIn(host, W, H, 'Grams of CO2e per passenger-kilometre');
  const ax = svg.append('g').attr('class', 'ax');
  for (const t of logTicks(x.domain())) {
    ax.append('line').attr('x1', x(t)).attr('x2', x(t)).attr('y1', top - 6).attr('y2', H - axisH);
    ax.append('text').attr('x', x(t)).attr('y', H - 8).attr('text-anchor', 'middle').text(`${nf.format(t)} g`);
  }
  for (const r of refs) {
    svg.append('line').attr('x1', x(r.gpkm)).attr('x2', x(r.gpkm)).attr('y1', top - 6).attr('y2', H - axisH).attr('stroke', css('--muted')).attr('stroke-width', 1.2);
    if (!narrow) svg.append('text').attr('class', 'lbl-muted').attr('x', x(r.gpkm) + 3).attr('y', H - axisH - 4).text(r.label);
  }
  items.forEach((it, i) => {
    const t = it.t, yT = top + i * rowH, yMid = narrow ? yT + 32 : yT + rowH / 2;
    const name = routeLabel(t);
    const mode = `${it.alt ? 'alternative · ' : ''}${legLabel(t)}${t.planned ? ' · planned' : ''}`;
    if (narrow) svg.append('text').attr('class', 'lbl').attr('x', 0).attr('y', yT + 13).text(`${name} · ${mode}`);
    else {
      svg.append('text').attr('class', 'lbl').attr('x', 0).attr('y', yMid - 2).text(name.length > 34 ? `${name.slice(0, 33)}…` : name);
      svg.append('text').attr('class', 'lbl-muted').attr('x', 0).attr('y', yMid + 12).text(mode.length > 38 ? `${mode.slice(0, 37)}…` : mode);
    }
    intervalMark(svg.append('g'), x, yMid, g_(it).map(v => Math.max(v, x.domain()[0])), it.alt ? css('--flying') : css('--actual'));
    const hit = svg.append('rect').attr('x', 0).attr('y', yT).attr('width', W).attr('height', rowH).attr('fill', 'transparent').datum(it);
    bindTip(hit, d => {
      const q = g_(d);
      return { head: `${name} · ${legLabel(d.t)}`, rows: [{ value: `${gpkm(q[1])} g/pkm`, label: `${gpkm(q[0])}–${gpkm(q[2])}`, color: d.alt ? css('--flying') : css('--actual') },
        { value: mass(tq(d.t)[1]), label: `over ${kmFmt(d.t.km)} km` }] };
    });
  });
}

// ---------------------------------------------------------------- tables with traces
function traceRow(tb, cols, t) {
  const trow = tb.insertRow(); trow.className = 'trace-row'; trow.hidden = true;
  const td = trow.insertCell(); td.colSpan = cols;
  const pre = document.createElement('p'); pre.className = 'trace'; pre.textContent = t.trace[tKey(t)];
  const src = document.createElement('span'); src.className = 'src';
  src.textContent = `\nCentral values shown; the table's median includes the uncertainty ranges.\nSources: ${t.sources.join(' · ') || 'none recorded'}`;
  pre.appendChild(src); td.appendChild(pre);
  return trow;
}
function travelTable(table, list, { showOption = false } = {}) {
  table.replaceChildren();
  const cols = [['Date'], ['From → to'], ['Mode'], ['km', 1], ['kg CO₂e', 1], ['g/pkm', 1], ['Grade'], ['']];
  if (showOption) cols.splice(1, 0, ['Option']);
  const tr = table.createTHead().insertRow();
  for (const [c, n] of cols) { const th = document.createElement('th'); th.textContent = c; if (n) th.className = 'num'; tr.appendChild(th); }
  const tb = table.createTBody();
  for (const t of list) {
    const q = tq(t);
    const row = tb.insertRow(); if (t.planned) row.className = 'planned';
    const cell = (txt, cls, sub) => {
      const td = row.insertCell(); if (cls) td.className = cls;
      td.append(document.createTextNode(txt));
      if (sub) { const s = document.createElement('span'); s.className = 'sm'; s.textContent = sub; td.appendChild(s); }
      return td;
    };
    cell(t.date ? fmtDate(t.date) : '–');
    if (showOption) { const c = cell(t.option); if (OPT.get(t.option)?.main) { const p = document.createElement('span'); p.className = 'pill solid'; p.textContent = 'main'; c.appendChild(p); } }
    const route = cell(routeLabel(t));
    if (t.planned) { const p = document.createElement('span'); p.className = 'pill'; p.textContent = 'planned'; route.appendChild(p); }
    const occ = t.occ_obs ? `${nf.format(t.occ_obs)}${t.occ_max ? ` of ${nf.format(t.occ_max)}` : ''} aboard` : '';
    cell(MODE_LABEL[t.mode] || t.mode, null, [t.profile, occ].filter(Boolean).join(' · '));
    cell(kmFmt(t.km), 'num');
    cell(mass(q[1]), 'num', range(q));
    cell(gpkm(q[1] / t.km * 1000), 'num');
    const gtd = row.insertCell(); const badge = document.createElement('span'); badge.className = 'badge'; badge.textContent = t.grade; badge.title = t.grade_note; gtd.appendChild(badge);
    const btd = row.insertCell(); const btn = document.createElement('button'); btn.type = 'button'; btn.className = 'how'; btn.textContent = 'How'; btn.setAttribute('aria-expanded', 'false'); btd.appendChild(btn);
    const trow = traceRow(tb, cols.length, t);
    btn.addEventListener('click', () => { const open = trow.hidden; trow.hidden = !open; btn.setAttribute('aria-expanded', String(open)); });
  }
}
function renderTables() {
  travelTable($('#legs-table'), DATA.travels.filter(t => t.type === 'leg' && inScope(t)));
  const alts = DATA.options.filter(o => S.scope === 'all' || !o.planned).flatMap(o => o.rows.map(id => TR.get(id)).filter(Boolean));
  travelTable($('#alts-table'), alts, { showOption: true });
}

function renderDash() {
  syncInputs();
  renderHero(); renderStrip(); renderRoute(); renderCumulative(); renderJourneys(); renderMethodCheck(); renderIntensity(); renderTables();
}

// ================================================================= owner: trip editor
const today = todayISO();

// Which data a vehicle name will pick up. Mirrors travel_dashboard/profiles.py for display only:
// the numbers themselves are always computed in Python.
const PROF = META?.profiles;
const reCache = new Map();
function matchesAny(patterns, text) {
  return (patterns || []).some((pat) => {
    let re = reCache.get(pat);
    if (!re) {
      try { re = new RegExp(`(?<![a-z0-9])${pat}(?![a-z0-9])`, 'i'); } catch { re = /(?!)/; }
      reCache.set(pat, re);
    }
    return re.test(text);
  });
}
function describeProfile(mode, vehicle, km, fuelL) {
  if (!PROF || !PROF.modes[mode]) return '';
  const base = PROF.modes[mode], text = vehicle || '';
  const hit = text && PROF.vehicles.find(v => (v.mode || mode) === mode && matchesAny(v.match, text));
  if (hit) return `Data: ${hit.name} · grade ${hit.grade}${hit.source ? ` · ${hit.source}` : ''}`;
  if (base.kind === 'flight') {
    const named = ['turboprop', 'wide', 'narrow'].find(c => matchesAny(PROF.flight.classes[c]?.match, text));
    const cls = named || (Number(km) >= PROF.flight.wide_from_km ? 'wide' : 'narrow');
    return `Data: ${PROF.flight.classes[cls].label} (${named ? 'from the aircraft name' : 'by distance; add the aircraft, e.g. A320'}) · per-flight fuel model · grade C`;
  }
  const logged = (base.kind === 'fuel' || base.kind === 'vehicle') && Number(fuelL) > 0;
  if (mode === 'car' && PROF.cars?.g_vkm) {
    const size = Object.entries(PROF.cars.sizes).find(([, p]) => matchesAny(p, text))?.[0] || PROF.cars.size_default;
    const fuel = Object.entries(PROF.cars.fuels).find(([, p]) => matchesAny(p, text))?.[0] || PROF.cars.fuel_default;
    const key = [`${size}_${fuel}`, `average_${fuel}`, 'average_petrol'].find(k => k in PROF.cars.g_vkm);
    return `Data: ${key.replace('_', ' ')} car · ${PROF.cars.g_vkm[key]} g CO₂e per km${logged && fuel !== 'electric' ? ' · litres logged: grade A' : ' · grade C'}`;
  }
  if (logged) return `Data: ${base.label} · litres logged: grade A`;
  return `Data: ${base.label} · grade ${base.grade}${base.grade === 'D' ? ' · nothing specific for this name yet: ask Claude to add it' : ''}`;
}
const kmText = t => (Number(t.km) ? `${kmFmt(Number(t.km))} km` : t.mode === 'plane' ? 'km from airports' : '– km');
function orderWaypoints(wps, legs) {
  const inc = new Map(), out = new Map();
  for (const l of legs) {
    if (!l.date) continue;
    if (!out.has(l.from)) out.set(l.from, []); out.get(l.from).push(l.date);
    if (!inc.has(l.to)) inc.set(l.to, []); inc.get(l.to).push(l.date);
  }
  const keyed = wps.map((w, i) => {
    let a = w.arrive || (inc.has(w.id) ? inc.get(w.id).sort().at(-1) : '');
    const d = w.depart || (out.has(w.id) ? out.get(w.id).sort()[0] : '9999-12-31');
    if (!a) a = out.has(w.id) || i === 0 ? '0000-01-01' : '9999-12-31';
    return { w, k: `${a}|${d}`, i };
  });
  keyed.sort((p, q) => (p.k < q.k ? -1 : p.k > q.k ? 1 : p.i - q.i));
  // ties: follow the legs
  for (let pass = 0; pass < keyed.length; pass++) {
    let moved = false;
    for (let i = 0; i + 1 < keyed.length; i++) {
      const p = keyed[i], q = keyed[i + 1];
      if (p.k === q.k && legs.some(l => l.from === q.w.id && l.to === p.w.id)) { keyed[i] = q; keyed[i + 1] = p; moved = true; }
    }
    if (!moved) break;
  }
  return keyed.map(x => x.w);
}

function editorData() {
  const wps = store.rows('waypoints');
  const travel = store.rows('travel');
  const legs = travel.filter(t => t.type === 'leg');
  const ordered = orderWaypoints(wps, legs);
  const pos = new Map(ordered.map((w, i) => [w.id, i]));
  return { wps: ordered, pos, travel, legs, alts: travel.filter(t => t.type === 'alt') };
}

const wpOption = w => ({ value: w.id, label: `${w.name}${w.arrive ? ` · ${fmtDate(w.arrive)}` : ''}` });

function waypointForm(existing, ed = editorData()) {
  const countries = [...new Set(ed.wps.map(w => w.country).filter(Boolean))];
  openForm({
    title: existing ? 'Edit waypoint' : 'Add waypoint',
    intro: 'A destination is a place you would have gone anyway. A stop exists because of how you travelled.',
    fields: [
      { name: 'name', label: 'Place', type: 'text', required: true, placeholder: 'e.g. Santa Cruz de La Palma' },
      { name: 'type', label: 'Type', type: 'chips', required: true, options: [{ value: 'destination', label: 'Destination' }, { value: 'stop', label: 'Stop' }] },
      { name: 'country', label: 'Country', type: 'datalist', datalist: countries },
      { type: 'row', fields: [
        { name: 'arrive', label: 'Arrive', type: 'date' },
        { name: 'depart', label: 'Depart', type: 'date' },
      ] },
      { name: 'airport', label: 'Airport (IATA code, optional)', type: 'text', placeholder: 'e.g. SPC',
        hint: 'Flights to or from here use this airport; their distance is then computed for you.' },
      { name: 'note', label: 'Note', type: 'text' },
    ],
    values: existing || { type: 'destination' },
    validate: v => (v.arrive && v.depart && v.depart < v.arrive ? 'Depart is before arrive'
      : v.airport && !/^[A-Za-z]{3}$/.test(v.airport) ? 'Airport: use a 3-letter code like SPC' : ''),
    onSave: v => {
      let id = existing?.id;
      if (!id) {
        const taken = new Set(ed.wps.map(w => w.id));
        const base = store.slug(v.name);
        id = base; for (let n = 2; taken.has(id); n++) id = `${base}-${n}`;
      }
      store.upsert('waypoints', { ...v, airport: (v.airport || '').toUpperCase(), id });
      toast(existing ? 'Saved' : `Added ${v.name}`);
    },
    onDelete: existing ? () => {
      const used = ed.travel.filter(t => t.from === existing.id || t.to === existing.id).length;
      if (used) throw new Error(`Used by ${used} travel row(s); change those first.`);
      store.remove('waypoints', existing.id); toast('Deleted');
    } : undefined,
  });
}

function travelForm(existing, preset = {}, ed = editorData()) {
  const wpOpts = [{ value: '', label: 'Choose…' }, ...ed.wps.map(wpOption)];
  const optionNames = [...new Set(ed.alts.map(a => a.option).filter(Boolean))];
  const pointList = [...ed.wps.map(w => ({ value: w.id, label: w.name })),
    ...[...new Set(ed.alts.flatMap(a => [a.from, a.to]).filter(p => !ed.pos.has(p)))].map(p => ({ value: p, label: 'via point' }))];
  const vehicles = (META?.vehicles || []).map(v => v.name);
  const values = existing ? { ...existing } : { type: 'leg', ...preset };
  values.from_leg = values.from_alt = values.from || '';
  values.to_leg = values.to_alt = values.to || '';
  if (existing && existing.type === 'leg' && existing.from && existing.from === existing.to) values.local = '1';
  const isAlt = v => v.type === 'alt';
  const kind = existing ? (existing.type === 'alt' ? 'alternative' : values.local ? 'local trip' : 'leg')
    : (values.type === 'alt' ? 'alternative' : values.local ? 'local trip' : 'leg');
  openForm({
    title: `${existing ? 'Edit' : 'Add'} ${kind}`,
    fields: [
      { name: 'type', label: 'Kind', type: 'chips', required: true, options: [{ value: 'leg', label: 'Leg (happened)' }, { value: 'alt', label: 'Alternative' }] },
      { name: 'option', label: 'Alternative name', type: 'datalist', datalist: optionNames, show: isAlt, required: true,
        hint: 'Segments with the same name form one alternative (e.g. a connection via Paris).' },
      { name: 'main', label: 'Main alternative for this journey', type: 'checkbox', show: isAlt },
      { type: 'row', fields: [
        { name: 'from_leg', label: 'From', type: 'select', options: wpOpts, show: v => !isAlt(v), required: true },
        { name: 'to_leg', label: 'To', type: 'select', options: wpOpts, show: v => !isAlt(v) && !v.local, required: true },
      ] },
      { name: 'local', label: 'Local trip: starts and ends here (e.g. driving around the island)', type: 'checkbox', show: v => !isAlt(v),
        hint: 'Local travel has no alternative: it counts the same in both worlds.' },
      { type: 'row', fields: [
        { name: 'from_alt', label: 'From', type: 'datalist', datalist: pointList, show: isAlt, required: true },
        { name: 'to_alt', label: 'To', type: 'datalist', datalist: pointList, show: isAlt, required: true,
          hint: 'Flights: write via airports as codes, e.g. BCN' },
      ] },
      { name: 'date', label: 'Date', type: 'date', show: v => !isAlt(v), required: true, default: today },
      { type: 'row', fields: [
        { name: 'mode', label: 'Mode', type: 'select', required: true, options: MODES.map(m => ({ value: m, label: MODE_LABEL[m] || m })) },
        { name: 'km', label: 'Distance (km)', type: 'number', required: v => v.mode !== 'plane',
          hint: 'Flights: leave empty to compute from airport codes' },
      ] },
      { name: 'vehicle', label: 'Vehicle, service or vessel', type: 'datalist', datalist: vehicles, placeholder: 'e.g. Bencomo Express, TGV Lyria, A320, Citroën C1 (95)' },
      { name: 'profile_info', type: 'info', text: v => describeProfile(v.mode, v.vehicle, v.km, v.fuel_l) },
      { type: 'row', fields: [
        { name: 'occ_max', label: 'Occupancy max', type: 'number', hint: 'seats, berths' },
        { name: 'occ_obs', label: 'Occupancy observed', type: 'number', hint: 'people aboard' },
      ] },
      { name: 'fuel_l', label: 'Fuel used (litres, whole vehicle)', type: 'number', show: v => ['sail', 'car', 'taxi'].includes(v.mode) },
      { name: 'note', label: 'Note', type: 'text' },
      { name: 'next', label: 'Add a connecting segment after saving', type: 'checkbox', show: v => isAlt(v) && !existing },
    ],
    values,
    validate: v => {
      if (isAlt(v)) return v.from_alt === v.to_alt ? 'An alternative needs a different start and end' : '';
      if (!v.local && v.from_leg === v.to_leg) return 'From and to are the same. For travel around one place, tick "Local trip".';
      return '';
    },
    onSave: v => {
      const alt = isAlt(v);
      const row = {
        id: existing?.id || `${alt ? 'A' : 'L'}${store.rand(4)}`, type: v.type, option: alt ? v.option : '',
        main: alt && v.main ? '1' : '', date: alt ? (existing?.date || '') : v.date,
        from: alt ? v.from_alt : v.from_leg, to: alt ? v.to_alt : (v.local ? v.from_leg : v.to_leg), mode: v.mode, vehicle: v.vehicle,
        km: v.km, occ_max: v.occ_max, occ_obs: v.occ_obs, fuel_l: v.fuel_l, note: v.note,
      };
      store.upsert('travel', row);
      if (alt) {
        // one alternative = all rows with that name: keep its main flag consistent
        for (const r of ed.alts.filter(a => a.option === v.option && a.id !== row.id && (a.main ? '1' : '') !== row.main)) store.upsert('travel', { ...r, main: row.main });
      }
      toast(existing ? 'Saved' : 'Added');
      if (alt && v.next) setTimeout(() => travelForm(null, { type: 'alt', option: v.option, main: v.main, from: row.to, mode: v.mode }), 50);
    },
    onDelete: existing ? () => { store.remove('travel', existing.id); toast('Deleted'); } : undefined,
    extra: existing && existing.type === 'leg' && existing.from !== existing.to ? {
      label: 'Copy as return trip',
      onClick: () => setTimeout(() => travelForm(null, {
        type: 'leg', from: existing.to, to: existing.from, mode: existing.mode, vehicle: existing.vehicle,
        km: existing.km, occ_max: existing.occ_max,
      }), 50),
    } : undefined,
  });
}

function edRow(parent, { title, detail, value, pending, onClick }) {
  const row = document.createElement('div'); row.className = `ed-row${pending ? ' pending' : ''}`; row.tabIndex = 0; row.setAttribute('role', 'button');
  const t = document.createElement('div'); t.className = 't'; t.textContent = title;
  const v = document.createElement('div'); v.className = 'v'; v.textContent = value || '';
  const d = document.createElement('div'); d.className = 'd'; d.textContent = detail || '';
  row.append(t, v, d);
  row.addEventListener('click', onClick);
  row.addEventListener('keydown', e => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); onClick(); } });
  parent.appendChild(row);
}
function travelDetail(t) {
  const occ = t.occ_obs ? `${t.occ_obs}${t.occ_max ? `/${t.occ_max}` : ''} aboard` : t.occ_max ? `max ${t.occ_max}` : '';
  return [MODE_LABEL[t.mode] || t.mode, t.vehicle, occ, t.note].filter(Boolean).join(' · ');
}

function renderEditor() {
  if (!store.isOwner()) return;
  const host = $('#ed-body');
  host.replaceChildren();
  const ed = editorData();
  const name = id => ed.wps.find(w => w.id === id)?.name || id;
  const tab = document.querySelector('input[name="ed-tab"]:checked')?.value || 'journeys';
  if (!ed.wps.length && !ed.travel.length) {
    const p = document.createElement('div'); p.className = 'card empty';
    const b = document.createElement('b'); b.textContent = store.hasData('waypoints') ? 'No trip data yet' : 'Loading trip data…';
    p.append(b, 'Start with your home as a destination, then add the places you went and the legs between them.');
    host.appendChild(p);
    return;
  }
  if (tab === 'waypoints') {
    const box = document.createElement('div'); box.className = 'ed-group';
    for (const w of ed.wps) {
      edRow(box, { title: w.name, value: w.type, pending: w._pending,
        detail: [w.country, dateSpan(w.arrive, w.depart), w.airport && `airport ${w.airport}`, w.note].filter(Boolean).join(' · '),
        onClick: () => waypointForm(w, ed) });
    }
    host.appendChild(box);
    return;
  }
  const dests = ed.wps.filter(w => w.type === 'destination');
  const placed = new Set();
  const group = (title, sub, a, b) => {
    const box = document.createElement('div'); box.className = 'ed-group';
    const head = document.createElement('header');
    const left = document.createElement('div');
    const h = document.createElement('h3'); h.textContent = title;
    const s = document.createElement('div'); s.className = 'muted'; s.textContent = sub;
    left.append(h, s);
    const btns = document.createElement('div'); btns.style.display = 'flex'; btns.style.gap = '6px';
    const addLeg = document.createElement('button'); addLeg.type = 'button'; addLeg.className = 'btn small'; addLeg.textContent = '+ Leg';
    addLeg.addEventListener('click', () => travelForm(null, { type: 'leg', from: a || '' }, ed));
    btns.appendChild(addLeg);
    if (a && b) {
      const addAlt = document.createElement('button'); addAlt.type = 'button'; addAlt.className = 'btn small'; addAlt.textContent = '+ Alternative';
      addAlt.addEventListener('click', () => {
        const base = `${store.slug(shortName(name(a)))}-${store.slug(shortName(name(b)))}`;
        const taken = new Set(ed.alts.map(x => x.option));
        let opt = base; for (let n = 2; taken.has(opt); n++) opt = `${base}-${n}`;
        travelForm(null, { type: 'alt', option: opt, main: ed.alts.some(x => x.from === a && x.main) ? '' : '1', from: a, to: b, mode: 'plane' }, ed);
      });
      btns.appendChild(addAlt);
    }
    head.append(left, btns);
    box.appendChild(head);
    host.appendChild(box);
    return box;
  };
  const between = (t, a, b) => t.from !== t.to && ed.pos.has(t.from) && ed.pos.has(t.to)
    && ed.pos.get(a) <= ed.pos.get(t.from) && ed.pos.get(t.to) <= ed.pos.get(b);
  // local travel (start = end) gets its own group after the journey that arrives there
  const locals = d3.group(ed.legs.filter(t => t.from === t.to && ed.pos.has(t.from)), t => t.from);
  const localGroups = (lo, hi) => {
    for (const w of ed.wps) {
      const p = ed.pos.get(w.id);
      if (p <= lo || p > hi || !locals.has(w.id)) continue;
      const list = locals.get(w.id).slice().sort((x, y) => String(x.date).localeCompare(String(y.date)));
      const box = document.createElement('div'); box.className = 'ed-group';
      const head = document.createElement('header');
      const left = document.createElement('div');
      const h = document.createElement('h3'); h.textContent = `Around ${shortName(w.name)}`;
      const s = document.createElement('div'); s.className = 'muted';
      s.textContent = `${list.length} local trip${list.length === 1 ? '' : 's'} · counted the same in both worlds`;
      left.append(h, s);
      const add = document.createElement('button'); add.type = 'button'; add.className = 'btn small'; add.textContent = '+ Local trip';
      add.addEventListener('click', () => travelForm(null, { type: 'leg', local: '1', from: w.id, to: w.id, mode: list.at(-1)?.mode || 'car' }, ed));
      head.append(left, add);
      box.appendChild(head);
      for (const t of list) {
        placed.add(t.id);
        edRow(box, { title: [t.date && fmtDate(t.date), MODE_LABEL[t.mode] || t.mode].filter(Boolean).join(' · '),
          value: kmText(t), pending: t._pending, detail: travelDetail(t), onClick: () => travelForm(t, {}, ed) });
      }
      host.appendChild(box);
    }
  };
  localGroups(-Infinity, dests.length ? ed.pos.get(dests[0].id) : Infinity);
  for (let i = 0; i + 1 < dests.length; i++) {
    const a = dests[i].id, b = dests[i + 1].id;
    const legs = ed.legs.filter(t => between(t, a, b)).sort((p, q) => (ed.pos.get(p.from) - ed.pos.get(q.from)) || String(p.date).localeCompare(String(q.date)));
    const opts = d3.group(ed.alts.filter(t => ed.pos.get(t.from) >= ed.pos.get(a) && ed.pos.get(t.from) < ed.pos.get(b)), t => t.option);
    const box = group(`${shortName(name(a))} → ${shortName(name(b))}`, `${legs.length} leg${legs.length === 1 ? '' : 's'} · ${opts.size} alternative${opts.size === 1 ? '' : 's'}`, a, b);
    if (legs.length) { const s = document.createElement('div'); s.className = 'ed-sub'; s.textContent = 'Legs'; box.appendChild(s); }
    for (const t of legs) {
      placed.add(t.id);
      edRow(box, { title: `${shortName(name(t.from))} → ${shortName(name(t.to))}`, value: kmText(t), pending: t._pending,
        detail: [t.date && fmtDate(t.date), travelDetail(t)].filter(Boolean).join(' · '), onClick: () => travelForm(t, {}, ed) });
    }
    for (const [optName, rows] of opts) {
      const s = document.createElement('div'); s.className = 'ed-sub';
      s.textContent = `Alternative: ${optName}${rows.some(r => r.main) ? ' (main)' : ''}`;
      box.appendChild(s);
      for (const t of rows) {
        placed.add(t.id);
        edRow(box, { title: `${shortName(name(t.from))} → ${shortName(name(t.to))}`, value: kmText(t), pending: t._pending,
          detail: travelDetail(t), onClick: () => travelForm(t, {}, ed) });
      }
    }
    localGroups(ed.pos.get(a), ed.pos.get(b));
  }
  if (dests.length) localGroups(ed.pos.get(dests[dests.length - 1].id), Infinity);
  // chain rows continue from via points: place them with their option
  const leftover = ed.travel.filter(t => !placed.has(t.id) && !(t.type === 'alt' && ed.alts.some(a => placed.has(a.id) && a.option === t.option)));
  const followers = ed.travel.filter(t => !placed.has(t.id) && !leftover.includes(t));
  for (const t of followers) {
    const box = [...host.querySelectorAll('.ed-sub')].find(s => s.textContent.startsWith(`Alternative: ${t.option}`));
    if (box) {
      const holder = document.createElement('div');
      edRow(holder, { title: `${shortName(name(t.from))} → ${shortName(name(t.to))}`, value: kmText(t), pending: t._pending,
        detail: travelDetail(t), onClick: () => travelForm(t, {}, ed) });
      let after = box; while (after.nextElementSibling && after.nextElementSibling.classList.contains('ed-row')) after = after.nextElementSibling;
      after.after(holder.firstChild);
    }
  }
  if (leftover.length) {
    const box = group('Not placed yet', 'Rows whose waypoints are missing or outside two destinations', '', '');
    for (const t of leftover) {
      edRow(box, { title: `${t.type === 'alt' ? `Alternative ${t.option}: ` : ''}${name(t.from)} → ${name(t.to)}`, value: kmText(t),
        pending: t._pending, detail: [t.date && fmtDate(t.date), travelDetail(t)].filter(Boolean).join(' · '), onClick: () => travelForm(t, {}, ed) });
    }
  }
}

function renderIssues() {
  const host = $('#issues');
  host.replaceChildren();
  const issues = DATA?.issues || [];
  if (!store.isOwner() || !issues.length) return;
  const box = document.createElement('div'); box.className = 'card';
  const h = document.createElement('p'); h.className = 'eyebrow'; h.textContent = `Data issues in the last build (${issues.length})`;
  const ul = document.createElement('ul'); ul.className = 'issues';
  for (const i of issues) { const li = document.createElement('li'); li.textContent = `${i.table} ${i.id}: ${i.message}`; ul.appendChild(li); }
  box.append(h, ul);
  host.appendChild(box);
}

// ---------------------------------------------------------------- wiring
initChrome(META);
const hasDash = DATA && DATA.waypoints?.length && DATA.travels?.length;
if (hasDash) {
  buildLensBar();
  renderDash();
  onResize(() => { renderStrip(); renderRoute(); renderCumulative(); renderJourneys(); renderMethodCheck(); renderIntensity(); });
  onThemeChange(renderDash);
  $('#mc-select').addEventListener('change', e => { mcSel = e.target.value; renderMethodCheck(); });
} else {
  $('#dash').hidden = true;
  document.querySelector('.lensbar').hidden = true;
  const e = $('#empty'); e.hidden = false;
  const box = document.createElement('div'); box.className = 'card empty'; box.style.marginTop = '20px';
  const b = document.createElement('b'); b.textContent = 'No trip data yet';
  box.append(b, store.isOwner() ? 'Add waypoints, legs and alternatives below. The charts appear after the next build.' : 'Check back soon.');
  e.appendChild(box);
}
wireTableToggles();
document.querySelectorAll('input[name="ed-tab"]').forEach(r => r.addEventListener('change', renderEditor));
$('#add-wp').addEventListener('click', () => waypointForm());
$('#add-leg').addEventListener('click', () => travelForm(null, { type: 'leg' }));
$('#add-alt').addEventListener('click', () => travelForm(null, { type: 'alt', mode: 'plane', main: '1' }));
$('#add-local').addEventListener('click', () => travelForm(null, { type: 'leg', local: '1', mode: 'car' }));
store.onChange(renderEditor);
renderEditor();
renderIssues();
const built = DATA?.meta?.built;
$('#foot').textContent = built ? `Data built ${new Date(built).toLocaleString('en-GB', { dateStyle: 'medium', timeStyle: 'short' })} · ${DATA.meta.draws} Monte Carlo draws` : 'No build yet';
if (store.isOwner()) store.syncAll(['waypoints', 'travel']);
