// Method page: the emission factors per passenger-km, and the trip's own ferries split three ways.
// Both are computed in Python (factors.py, model.ship_breakdown); this page only draws them.
import { $, loadJSON, initChrome, svgIn, css, bindTip, fmtDate, mass, nf, sig, onResize, onThemeChange } from './common.js';

const [META, DATA] = await Promise.all([loadJSON('../data/meta.json'), loadJSON('../data/emissions.json')]);
const METHODS = [['passenger', 'Per passenger'], ['iso', 'ISO 14083'], ['mass', 'By mass']];
const ships = (DATA?.travels || []).filter(t => t.type === 'leg' && t.ship);
const short = n => String(n || '').split(',')[0];
const pct = x => (x >= 0.995 ? '100 %' : x >= 0.1 ? `${Math.round(x * 100)} %` : `${(x * 100).toFixed(1)} %`);

function drawBars(host, b) {
  const colors = [css('--actual'), css('--rule'), css('--muted')];
  const W = Math.max(host.clientWidth, 280), narrow = W < 600;
  const labelW = narrow ? 0 : 118, textW = narrow ? 0 : 250, rowH = narrow ? 50 : 36, barH = 18;
  const H = METHODS.length * rowH + 4;
  const x0 = labelW, x1 = W - textW;
  const svg = svgIn(host, W, H, 'One sailing split between passengers and vehicles under each method');
  METHODS.forEach(([id, label], i) => {
    const m = b.methods[id];
    const yT = i * rowH, yBar = narrow ? yT + 22 : yT + (rowH - barH) / 2;
    const isDefault = id === (DATA.defaults?.alloc || 'iso');
    svg.append('text').attr('class', isDefault ? 'lbl-strong' : 'lbl').attr('x', 0).attr('y', narrow ? yT + 14 : yBar + 13).text(label);
    let x = x0;
    m.shares.forEach((share, k) => {
      if (share <= 0) return;
      const w = share * (x1 - x0);
      svg.append('rect').attr('x', x).attr('y', yBar).attr('width', Math.max(1.5, w - 2)).attr('height', barH)
        .attr('rx', 3).attr('fill', colors[Math.min(k, colors.length - 1)]);
      x += w;
    });
    const text = `${mass(m.kg)} each · ${pct(m.shares[0])} on passengers`;
    if (narrow) svg.append('text').attr('class', isDefault ? 'lbl-strong' : 'lbl').attr('x', W).attr('y', yT + 14).attr('text-anchor', 'end').text(`${mass(m.kg)} each`);
    else svg.append('text').attr('class', isDefault ? 'lbl-strong' : 'lbl').attr('x', x1 + 12).attr('y', yBar + 13).text(text);
    const hit = svg.append('rect').attr('x', 0).attr('y', yT).attr('width', W).attr('height', rowH).attr('fill', 'transparent').datum(m);
    bindTip(hit, d => ({
      head: `${label}: ${mass(d.kg)} per passenger`,
      rows: b.groups.map((g, k) => ({ value: pct(d.shares[k]), label: `${Math.round(g.count)} ${g.label}`, color: colors[Math.min(k, colors.length - 1)] })),
    }));
  });
}

function renderShips() {
  const host = $('#ships');
  host.replaceChildren();
  if (!ships.length) {
    const p = document.createElement('p'); p.className = 'card empty'; p.textContent = 'No ferry legs in the data yet.';
    host.appendChild(p);
    return;
  }
  for (const t of ships) {
    const b = t.ship.observed;
    const [pax, ...vehicles] = b.groups;
    const card = document.createElement('figure'); card.className = 'card ship-card';
    const h = document.createElement('h3');
    h.textContent = `${short(t.from_name)} → ${short(t.to_name)} · ${t.profile} · ${fmtDate(t.date)}`;
    const facts = document.createElement('p'); facts.className = 'ship-facts';
    facts.textContent = `${nf.format(b.fuel_t)} t of fuel → ${nf.format(Math.round(b.e_kg / 100) / 10)} t CO₂e for the sailing · `
      + `${Math.round(pax.count)} passengers (${b.observed ? 'counted on board' : 'typical'}) · `
      + `${vehicles.map(v => `about ${Math.round(v.count)} ${v.label}`).join(' and ')} (typical for this ship)`;
    const chart = document.createElement('div'); chart.className = 'chart';
    card.append(h, facts, chart);
    host.appendChild(card);
    drawBars(chart, b);
  }
}

function renderOccupancy() {
  const el = $('#occ-example');
  // The sailing where the head count changes the result most makes the clearest example.
  const gap = s => Math.abs(s.ship.observed.methods.iso.kg / s.ship.typical.methods.iso.kg - 1);
  const t = ships.filter(s => s.ship.observed.observed).sort((a, b) => gap(b) - gap(a))[0];
  if (!t) { el.textContent = ''; return; }
  const obs = t.ship.observed, typ = t.ship.typical;
  el.textContent = `Example: on ${fmtDate(t.date)} the ${t.profile} carried ${Math.round(obs.groups[0].count)} passengers, `
    + `against about ${Math.round(typ.groups[0].count)} on an average sailing. Under ISO 14083 that's ${mass(obs.methods.iso.kg)} `
    + `per passenger as observed, against ${mass(typ.methods.iso.kg)} with typical occupancy.`;
  const fc = ships.find(s => s !== t && s.ship.observed.methods.iso.shares[0] < 0.25);
  if (fc) el.textContent += ` On a freight ferry like the ${fc.profile} the head count barely matters, because the trucks carry most of the ship.`;
}

// Default factors: computed in Python (factors.py) with the same model as the dashboard.
const LENS_TEXT = { passenger: 'on passengers only', iso: 'split by ISO 14083', mass: 'split by mass',
  co2: 'CO₂ only', full: 'with non-CO₂' };
function el(tag, cls, text) {
  const e = document.createElement(tag);
  if (cls) e.className = cls;
  if (text != null) e.textContent = text;
  return e;
}
function renderFactors() {
  const F = DATA?.factors, host = $('#factors-table');
  if (!F) { host.textContent = 'No factors in the data yet.'; return; }
  const group = document.querySelector('input[name="fgroup"]:checked')?.value || 'default';
  $('#factors-note').textContent = `At typical load. Bold: the central value from the config; below it the middle 90 % `
    + `of ${nf.format(F.draws)} draws. Ferries ${LENS_TEXT[F.alloc]}, flights ${LENS_TEXT[F.nonco2]}, as the Emissions `
    + `page opens. Flights get one row per distance: take-off and landing cost the same on any flight.`;
  const table = el('table', 'data');
  const head = table.createTHead().insertRow();
  head.append(el('th', null, group === 'named' ? 'Vehicle' : 'Mode'), el('th', 'num', 'g/pkm'));
  const body = table.createTBody();
  for (const r of F.rows.filter(x => x.group === group)) {
    const row = body.insertRow();
    const name = row.insertCell();
    const badge = el('span', 'badge', r.grade);
    badge.title = `Data quality ${r.grade}`;
    name.append(el('b', null, r.title), badge);
    const other = r.other.map(o => `${o.label} ${sig(o.g, 3)}`).join(' · ');
    for (const line of [r.basis, other && `Other switches: ${other}`, r.source && `Source: ${r.source}`]) {
      if (line) name.appendChild(el('span', 'sm', line));
    }
    const val = row.insertCell();
    val.className = 'num';
    val.appendChild(el('b', null, sig(r.g, 3)));
    if (r.range[1] > 0) val.appendChild(el('span', 'sm', `${sig(r.range[0])}–${sig(r.range[1])}`));
  }
  const wrap = el('div', 'tblwrap');
  wrap.appendChild(table);
  host.replaceChildren(wrap);
}
function render() { renderShips(); renderOccupancy(); renderFactors(); }

initChrome(META);
render();
$('#factors-seg').addEventListener('change', renderFactors);
// The charts render (and web fonts load) after the browser jumped to the anchor, so jump again.
const target = location.hash && document.getElementById(location.hash.slice(1));
if (target) { target.scrollIntoView(); document.fonts?.ready.then(() => target.scrollIntoView()); }
onResize(renderShips);
onThemeChange(renderShips);
const built = DATA?.meta?.built;
$('#foot').textContent = built ? `Data built ${new Date(built).toLocaleString('en-GB', { dateStyle: 'medium', timeStyle: 'short' })}` : '';
