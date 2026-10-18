// Shared helpers: formatting, tooltip, chart primitives, page chrome (nav, owner mode, sync pill).
import * as store from './store.js';
import { openOwnerDialog } from './editor.js';

export const $ = (sel, el = document) => el.querySelector(sel);
export const $$ = (sel, el = document) => [...el.querySelectorAll(sel)];

// ---------------------------------------------------------------- formatting
export const nf = new Intl.NumberFormat('en-US', { maximumFractionDigits: 3 });
const nf0 = new Intl.NumberFormat('en-US', { maximumFractionDigits: 0 });
const nf2 = new Intl.NumberFormat('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
export const sig = (v, n = 2) => (v == null || !isFinite(v)) ? '–' : v === 0 ? '0' : nf.format(Number(v.toPrecision(n)));
export const neg = s => s.replace(/^-/, '−');
export function mass(v, ref = v) {
  return Math.abs(ref) >= 1000 ? `${neg(sig(v / 1000))} t` : `${neg(sig(v))} kg`;
}
export function range(q) {
  const ref = Math.max(Math.abs(q[0]), Math.abs(q[2]));
  const t = ref >= 1000;
  const f = v => neg(t ? sig(v / 1000) : sig(v));
  const sep = q[0] < 0 || q[2] < 0 ? ' to ' : '–';
  return `${f(q[0])}${sep}${f(q[2])} ${t ? 't' : 'kg'}`;
}
export const tonnes = v => neg(sig(v / 1000));
export const kmFmt = v => nf0.format(Math.round(v));
export const gpkm = v => neg(sig(v));
export const chf = (v, d = 0) => `CHF ${d ? nf2.format(v) : nf0.format(v)}`;
export const chf2 = v => nf2.format(v);
export function fmtDate(iso, opts = { day: 'numeric', month: 'short' }) {
  if (!iso) return '–';
  return new Date(`${iso}T12:00:00Z`).toLocaleDateString('en-GB', { ...opts, timeZone: 'UTC' });
}
export function todayISO() {
  const d = new Date();
  return new Date(d.getTime() - d.getTimezoneOffset() * 60000).toISOString().slice(0, 10);
}

// ---------------------------------------------------------------- tooltip
let tip;
function tipEl() {
  if (!tip) { tip = document.createElement('div'); tip.id = 'tip'; tip.setAttribute('role', 'tooltip'); tip.hidden = true; document.body.appendChild(tip); }
  return tip;
}
export function showTip(evt, head, rows) {
  const t = tipEl();
  t.replaceChildren();
  if (head) { const h = document.createElement('div'); h.className = 't-h'; h.textContent = head; t.appendChild(h); }
  for (const r of rows) {
    const row = document.createElement('div'); row.className = 't-r';
    if (r.color) { const k = document.createElement('i'); k.className = 't-k'; k.style.borderColor = r.color; row.appendChild(k); }
    const v = document.createElement('span'); v.className = 't-v'; v.textContent = r.value; row.appendChild(v);
    if (r.label) { const l = document.createElement('span'); l.className = 't-l'; l.textContent = r.label; row.appendChild(l); }
    t.appendChild(row);
  }
  t.hidden = false;
  let x, y;
  if (evt && evt.clientX != null && evt.type !== 'focus') { x = evt.clientX; y = evt.clientY; }
  else { const b = evt.target.getBoundingClientRect(); x = b.left + b.width / 2; y = b.top; }
  const w = t.offsetWidth, h = t.offsetHeight, pad = 12;
  let left = x + 14, top = y - h - 10;
  if (left + w > innerWidth - pad) left = x - w - 14;
  if (left < pad) left = pad;
  if (top < pad) top = y + 16;
  t.style.left = `${left}px`; t.style.top = `${top}px`;
}
export const hideTip = () => { if (tip) tip.hidden = true; };
export function bindTip(sel, fn) {
  sel.attr('tabindex', 0)
    .on('pointerenter pointermove focus', function (evt, d) { const c = fn(d); showTip(evt, c.head, c.rows); })
    .on('pointerleave blur', hideTip);
}

// ---------------------------------------------------------------- chart primitives (d3 is a global)
export const css = v => getComputedStyle(document.documentElement).getPropertyValue(v).trim();
export function svgIn(host, w, h, label) {
  host.replaceChildren();
  return d3.select(host).append('svg').attr('width', w).attr('height', h).attr('viewBox', `0 0 ${w} ${h}`)
    .attr('role', 'img').attr('aria-label', label || '');
}
/** Labelled ticks of a log scale: 1-2-5 per decade where they fit (one per ~46 px), else 1-3, else powers of ten. */
export function logTicks(domain, px = 640) {
  for (const ms of [[1, 2, 5], [1, 3], [1]]) {
    const out = [];
    for (let e = Math.floor(Math.log10(domain[0])); e <= Math.ceil(Math.log10(domain[1])); e++) {
      for (const m of ms) { const v = m * 10 ** e; if (v >= domain[0] * 0.999 && v <= domain[1] * 1.001) out.push(v); }
    }
    if (ms.length === 1 || out.length <= Math.max(3, px / 46)) return out;
  }
}
/** Unlabelled minor ticks of a log scale: every whole multiple within each decade. */
export function logMinor(domain) {
  const out = [];
  for (let e = Math.floor(Math.log10(domain[0])); e <= Math.ceil(Math.log10(domain[1])); e++) {
    for (let m = 1; m <= 9; m++) { const v = m * 10 ** e; if (v >= domain[0] && v <= domain[1]) out.push(v); }
  }
  return out;
}
/** Short tick marks hanging below an axis line at y, for minor ticks. */
export function minorMarks(ax, xs, y) {
  for (const px of xs) ax.append('line').attr('class', 'minor').attr('x1', px).attr('x2', px).attr('y1', y).attr('y2', y + 4);
}
export const tickKg = v => (v >= 1000 ? `${nf.format(v / 1000)} t` : `${nf.format(v)} kg`);
export function intervalMark(g, x, y, q, color, r = 5, hollow = false) {
  g.append('line').attr('x1', x(q[0])).attr('x2', x(q[2])).attr('y1', y).attr('y2', y)
    .attr('stroke', color).attr('stroke-width', hollow ? 1.5 : 2.5).attr('stroke-linecap', 'round')
    .attr('stroke-opacity', hollow ? 0.6 : 1);
  g.append('circle').attr('cx', x(q[1])).attr('cy', y).attr('r', r)
    .attr('fill', hollow ? css('--surface') : color).attr('stroke', hollow ? color : css('--surface')).attr('stroke-width', 2);
}
export function makeTable(host, cols, rows) {
  host.replaceChildren();
  const wrap = document.createElement('div'); wrap.className = 'tblwrap';
  const t = document.createElement('table'); t.className = 'data';
  const tr = t.createTHead().insertRow();
  for (const c of cols) { const th = document.createElement('th'); th.textContent = c.label; if (c.num) th.className = 'num'; tr.appendChild(th); }
  const tb = t.createTBody();
  for (const r of rows) {
    const row = tb.insertRow();
    cols.forEach((c, i) => { const td = row.insertCell(); td.textContent = r[i]; if (c.num) td.className = 'num'; });
  }
  wrap.appendChild(t); host.appendChild(wrap);
}
/** "Table" and "Method" buttons: data-table="x" shows #x-table, data-toggle="id" shows #id. */
export function wireTableToggles(root = document) {
  $$('.tbtn[data-table], .tbtn[data-toggle]', root).forEach(b => b.addEventListener('click', () => {
    const on = b.getAttribute('aria-pressed') !== 'true';
    b.setAttribute('aria-pressed', String(on));
    document.getElementById(b.dataset.toggle || `${b.dataset.table}-table`).hidden = !on;
  }));
}

// ---------------------------------------------------------------- misc UI
/** Append a source text to el, its [label](https://…) parts as links. Builds nodes, never HTML. */
export function appendLinked(el, text) {
  const re = /\[([^\]]+)\]\((https?:\/\/[^)\s]+)\)/g;
  let last = 0, m;
  while ((m = re.exec(text))) {
    if (m.index > last) el.append(text.slice(last, m.index));
    const a = document.createElement('a');
    a.href = m[2]; a.textContent = m[1]; a.target = '_blank'; a.rel = 'noopener';
    el.appendChild(a);
    last = re.lastIndex;
  }
  if (last < text.length) el.append(text.slice(last));
  return el;
}
let toastTimer;
export function toast(msg) {
  let el = document.getElementById('toast');
  if (!el) { el = document.createElement('div'); el.id = 'toast'; el.setAttribute('role', 'status'); document.body.appendChild(el); }
  el.textContent = msg; el.hidden = false;
  clearTimeout(toastTimer); toastTimer = setTimeout(() => { el.hidden = true; }, 2600);
}
export async function loadJSON(url) {
  try {
    const res = await fetch(url, { cache: 'no-cache' });
    return res.ok ? await res.json() : null;
  } catch { return null; }
}
export function onResize(fn) {
  let raf = 0, lastW = innerWidth;
  addEventListener('resize', () => {
    if (innerWidth === lastW) return;
    lastW = innerWidth;
    cancelAnimationFrame(raf); raf = requestAnimationFrame(fn);
  });
}
export function onThemeChange(fn) {
  const mq = matchMedia('(prefers-color-scheme: dark)');
  if (mq.addEventListener) mq.addEventListener('change', fn);
  new MutationObserver(fn).observe(document.documentElement, { attributes: true, attributeFilter: ['data-theme'] });
}

/** Shared page setup: owner mode, sync pill, owner link, service worker. */
export function initChrome(meta) {
  const apply = () => {
    document.body.classList.toggle('owner', store.isOwner());
    const pill = document.getElementById('sync-pill');
    if (pill && store.isOwner()) {
      const st = store.overallStatus();
      pill.dataset.state = st.state;
      pill.textContent = st.label;
      pill.title = st.error || 'Changes are saved to the repo; the charts update after the next build (~2 min).';
    }
  };
  store.onChange(apply);
  apply();
  const pill = document.getElementById('sync-pill');
  if (pill) pill.addEventListener('click', () => store.syncAll());
  for (const el of $$('[data-owner-link]')) el.addEventListener('click', e => { e.preventDefault(); openOwnerDialog(meta); });
  if ('serviceWorker' in navigator && location.protocol !== 'file:') {
    navigator.serviceWorker.register(new URL('../sw.js', import.meta.url), { scope: new URL('../', import.meta.url).pathname })
      .catch(() => { /* offline support is optional */ });
  }
}
