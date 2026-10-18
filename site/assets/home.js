// Landing page: two doors with one headline number each.
import { $, chf, fmtDate, loadJSON, initChrome, tonnes } from './common.js';

const [META, COSTS, EM] = await Promise.all([
  loadJSON('data/meta.json'), loadJSON('data/costs.json'), loadJSON('data/emissions.json'),
]);
initChrome(META);

const s = COSTS?.summary;
if (s) {
  $('#costs-big').replaceChildren(chf(s.total), ' ');
  const small = document.createElement('small'); small.textContent = `· ${chf(s.per_day)} per day`;
  $('#costs-big').appendChild(small);
  $('#costs-sub').textContent = `${s.entries} entries in ${s.countries} ${s.countries === 1 ? 'country' : 'countries'} since ${fmtDate(s.first)}`;
}
if (EM?.totals && EM.defaults && EM.meta?.counts?.legs) {
  const d = EM.defaults;
  const t = EM.totals[`${d.level}|${d.alloc}|${d.occ}|${d.nonco2}|todate`];
  const all = EM.totals[`${d.level}|${d.alloc}|${d.occ}|${d.nonco2}|all`];
  if (t) {
    $('#em-big').replaceChildren(`${tonnes(t.avoided[1])} t`, ' ');
    const small = document.createElement('small'); small.textContent = 'CO₂e avoided so far';
    $('#em-big').appendChild(small);
    if (all && Math.abs(all.avoided[1] - t.avoided[1]) > 0.5) {
      $('#em-sub').textContent = `${tonnes(all.avoided[1])} t including planned travel · recommended method, median`;
    }
  }
}
const built = EM?.meta?.built || COSTS?.meta?.built;
$('#foot').textContent = built ? `Data built ${new Date(built).toLocaleString('en-GB', { dateStyle: 'medium', timeStyle: 'short' })}` : '';
