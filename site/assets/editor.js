// Small form builder for the owner's editing dialogs, plus the owner sign-in dialog.
import * as store from './store.js';

let uid = 0;
const fid = name => `f-${name}-${++uid}`;

/**
 * Open a modal form. fields: [{name, label, type, options, required, hint, show(values), ...}]
 * types: text | number | big-number | date | select | chips | checkbox | password | datalist | row
 */
export function openForm({ title, intro, fields, values = {}, submitLabel = 'Save', onSave, onDelete, deleteLabel = 'Delete', validate }) {
  const dlg = document.createElement('dialog');
  dlg.className = 'sheet';
  const form = document.createElement('form');
  form.noValidate = true;
  const h = document.createElement('h2'); h.textContent = title; form.appendChild(h);
  if (intro) { const p = document.createElement('p'); p.className = 'muted'; p.append(intro); form.appendChild(p); }

  const flat = [];
  const render = (f) => {
    if (f.type === 'row') {
      const row = document.createElement('div'); row.className = 'row2';
      for (const sub of f.fields) row.appendChild(render(sub));
      return row;
    }
    flat.push(f);
    const wrap = document.createElement('div'); wrap.className = 'field'; wrap.dataset.name = f.name;
    const id = fid(f.name);
    f._id = id; f._wrap = wrap;
    const v = values[f.name] ?? f.default ?? '';
    if (f.type === 'chips') {
      const lab = document.createElement('div'); lab.className = 'flabel'; lab.textContent = f.label; wrap.appendChild(lab);
      const box = document.createElement('div'); box.className = 'chips'; box.setAttribute('role', 'radiogroup');
      box.setAttribute('aria-label', f.label);
      for (const o of f.options) {
        const inp = document.createElement('input');
        inp.type = 'radio'; inp.name = id; inp.id = `${id}-${o.value}`; inp.value = o.value; inp.checked = String(v) === String(o.value);
        const l = document.createElement('label'); l.htmlFor = inp.id; l.textContent = o.label;
        box.append(inp, l);
      }
      wrap.appendChild(box);
    } else if (f.type === 'checkbox') {
      const line = document.createElement('label'); line.className = 'checkline'; line.htmlFor = id;
      const inp = document.createElement('input'); inp.type = 'checkbox'; inp.id = id; inp.checked = !!v && v !== '0';
      line.append(inp, document.createTextNode(f.label));
      wrap.appendChild(line);
    } else {
      const lab = document.createElement('label'); lab.htmlFor = id; lab.textContent = f.label; wrap.appendChild(lab);
      let inp;
      if (f.type === 'select') {
        inp = document.createElement('select');
        for (const o of f.options) {
          const op = document.createElement('option'); op.value = o.value; op.textContent = o.label;
          inp.appendChild(op);
        }
        inp.value = v;
      } else {
        inp = document.createElement('input');
        inp.type = { number: 'number', 'big-number': 'text', date: 'date', password: 'password' }[f.type] || 'text';
        if (f.type === 'number') { inp.step = f.step || 'any'; inp.min = f.min ?? 0; inp.inputMode = 'decimal'; }
        if (f.type === 'big-number') { inp.inputMode = 'decimal'; inp.className = 'big'; inp.autocomplete = 'off'; }
        if (f.type === 'password') inp.autocomplete = 'off';
        if (f.placeholder) inp.placeholder = f.placeholder;
        if (f.datalist) {
          const dl = document.createElement('datalist'); dl.id = `${id}-list`;
          for (const o of f.datalist) {
            const op = document.createElement('option');
            op.value = typeof o === 'string' ? o : o.value;
            if (typeof o !== 'string' && o.label) op.label = o.label;
            dl.appendChild(op);
          }
          inp.setAttribute('list', dl.id);
          wrap.appendChild(dl);
        }
        inp.value = v;
      }
      inp.id = id;
      wrap.appendChild(inp);
    }
    if (f.hint) { const hn = document.createElement('div'); hn.className = 'hint'; hn.textContent = f.hint; wrap.appendChild(hn); }
    return wrap;
  };
  for (const f of fields) form.appendChild(render(f));

  const err = document.createElement('p'); err.className = 'form-error'; err.hidden = true; err.setAttribute('role', 'alert');
  form.appendChild(err);
  const actions = document.createElement('div'); actions.className = 'actions';
  if (onDelete) {
    const del = document.createElement('button'); del.type = 'button'; del.className = 'btn danger'; del.textContent = deleteLabel;
    del.addEventListener('click', async () => {
      if (del.dataset.confirm !== '1') { del.dataset.confirm = '1'; del.textContent = `Tap again: ${deleteLabel.toLowerCase()}`; return; }
      try { await onDelete(); dlg.close(); }
      catch (ex) { err.textContent = ex.message || String(ex); err.hidden = false; }
    });
    actions.appendChild(del);
  }
  const right = document.createElement('div'); right.className = 'right';
  const cancel = document.createElement('button'); cancel.type = 'button'; cancel.className = 'btn'; cancel.textContent = 'Cancel';
  cancel.addEventListener('click', () => dlg.close());
  const save = document.createElement('button'); save.type = 'submit'; save.className = 'btn primary'; save.textContent = submitLabel;
  right.append(cancel, save); actions.appendChild(right); form.appendChild(actions);

  const read = () => {
    const out = {};
    for (const f of flat) {
      if (f.type === 'chips') {
        const c = f._wrap.querySelector('input:checked'); out[f.name] = c ? c.value : '';
      } else if (f.type === 'checkbox') out[f.name] = document.getElementById(f._id).checked ? '1' : '';
      else out[f.name] = document.getElementById(f._id).value.trim();
    }
    return out;
  };
  const refreshVisibility = () => {
    const vals = read();
    for (const f of flat) if (f.show) f._wrap.hidden = !f.show(vals);
    for (const row of form.querySelectorAll('.row2')) row.hidden = [...row.children].every(c => c.hidden);
  };
  form.addEventListener('input', refreshVisibility);
  form.addEventListener('change', refreshVisibility);

  form.addEventListener('submit', async (e) => {
    e.preventDefault();
    const vals = read();
    for (const f of flat) if (f._wrap.hidden) vals[f.name] = '';
    let problem = '';
    for (const f of flat) {
      f._wrap.classList.remove('invalid');
      if (f._wrap.hidden) continue;
      const missing = f.required && !vals[f.name];
      const badNum = (f.type === 'number' || f.type === 'big-number') && vals[f.name] && !isFinite(Number(vals[f.name].replace(',', '.')));
      if (missing || badNum) { f._wrap.classList.add('invalid'); problem ||= `${f.label}: ${missing ? 'required' : 'not a number'}`; }
    }
    if (!problem && validate) problem = validate(vals) || '';
    if (problem) { err.textContent = problem; err.hidden = false; return; }
    for (const f of flat) if ((f.type === 'number' || f.type === 'big-number') && vals[f.name]) vals[f.name] = vals[f.name].replace(',', '.');
    save.disabled = true;
    try { await onSave(vals); dlg.close(); }
    catch (ex) { err.textContent = ex.message || String(ex); err.hidden = false; save.disabled = false; }
  });

  dlg.appendChild(form);
  document.body.appendChild(dlg);
  dlg.addEventListener('close', () => dlg.remove());
  refreshVisibility();
  dlg.showModal();
  const first = form.querySelector('input.big, input[type="text"], input[type="number"], select');
  if (first && !('ontouchstart' in window && first.type === 'date')) first.focus();
  return dlg;
}

/** Sign in on this device with a fine-grained token, or sign out. */
export function openOwnerDialog(meta) {
  const s = store.getSettings();
  const repo = meta?.repo || {};
  if (store.isOwner()) {
    const pending = store.pendingCount();
    openForm({
      title: 'Editing on this device',
      intro: `Connected to ${s.owner}/${s.repo} (${s.branch}).${pending ? ` ${pending} change(s) are waiting to be saved.` : ''}`,
      fields: [],
      submitLabel: 'Sync now',
      onSave: () => store.syncAll(),
      deleteLabel: 'Disconnect this device',
      onDelete: async () => {
        store.signOut();
        location.reload();
      },
    });
    return;
  }
  const intro = document.createDocumentFragment();
  intro.append('Only the owner can edit. Create a ');
  const a = document.createElement('a');
  a.href = 'https://github.com/settings/personal-access-tokens/new';
  a.target = '_blank'; a.rel = 'noopener'; a.textContent = 'fine-grained GitHub token';
  intro.append(a, ' with access to this one repository and the permission "Contents: Read and write", then paste it here. It stays in this browser.');
  openForm({
    title: 'Owner sign-in',
    intro,
    fields: [
      { name: 'token', label: 'GitHub token', type: 'password', required: true, placeholder: 'github_pat_…' },
      { type: 'row', fields: [
        { name: 'owner', label: 'Account', type: 'text', required: true, default: repo.owner || '' },
        { name: 'repo', label: 'Repository', type: 'text', required: true, default: repo.name || '' },
      ] },
      { name: 'branch', label: 'Branch', type: 'text', required: true, default: repo.branch || 'main' },
    ],
    submitLabel: 'Connect',
    onSave: async (v) => {
      const settings = { token: v.token, owner: v.owner, repo: v.repo, branch: v.branch, dataDir: repo.data_dir || 'data' };
      await store.testConnection(settings);
      store.saveSettings(settings);
      await store.syncAll();
      location.reload();
    },
  });
}
