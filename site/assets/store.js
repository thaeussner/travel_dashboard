// Owner-only editing: read and write the CSV tables in the GitHub repo from the browser.
// Every change is queued in this browser first (so it works offline), then pushed as one commit
// per table through the GitHub contents API, using a fine-grained token that only the owner has.
// Keep COLUMNS in sync with travel_dashboard/tables.py.

export const COLUMNS = {
  costs: ['id', 'date', 'amount', 'category', 'country'],
  waypoints: ['id', 'name', 'type', 'country', 'arrive', 'depart', 'note', 'airport'],
  travel: ['id', 'type', 'option', 'main', 'date', 'from', 'to', 'mode', 'vehicle', 'km',
           'occ_max', 'occ_obs', 'fuel_l', 'note'],
};
const API = 'https://api.github.com';
const K = { settings: 'td:settings', table: n => `td:table:${n}`, queue: n => `td:queue:${n}` };

// ---------------------------------------------------------------- local storage (may be blocked)
function lsGet(key, fallback) {
  try { const v = localStorage.getItem(key); return v ? JSON.parse(v) : fallback; } catch { return fallback; }
}
function lsSet(key, value) {
  try { localStorage.setItem(key, JSON.stringify(value)); return true; } catch { return false; }
}
function lsDel(key) { try { localStorage.removeItem(key); } catch { /* ignore */ } }

// ---------------------------------------------------------------- change notifications
const listeners = new Set();
export function onChange(fn) { listeners.add(fn); return () => listeners.delete(fn); }
function emit() { for (const fn of listeners) { try { fn(); } catch (e) { console.error(e); } } }

// ---------------------------------------------------------------- settings
export function getSettings() { return lsGet(K.settings, {}); }
export function isOwner() { return !!getSettings().token; }
export function saveSettings(s) { lsSet(K.settings, s); emit(); }
export function signOut() {
  lsDel(K.settings);
  for (const n of Object.keys(COLUMNS)) lsDel(K.table(n));
  emit();
}

// ---------------------------------------------------------------- CSV
export function parseCSV(text) {
  const rows = [];
  let row = [], field = '', quoted = false;
  text = text.replace(/^﻿/, '');
  for (let i = 0; i < text.length; i++) {
    const c = text[i];
    if (quoted) {
      if (c === '"') {
        if (text[i + 1] === '"') { field += '"'; i++; } else quoted = false;
      } else field += c;
    } else if (c === '"') quoted = true;
    else if (c === ',') { row.push(field); field = ''; }
    else if (c === '\n') { row.push(field); rows.push(row); row = []; field = ''; }
    else if (c !== '\r') field += c;
  }
  if (field !== '' || row.length) { row.push(field); rows.push(row); }
  return rows.filter(r => r.some(v => v.trim() !== ''));
}

function toObjects(rows) {
  if (!rows.length) return { header: [], items: [] };
  const header = rows[0].map(h => h.trim().toLowerCase());
  const items = rows.slice(1).map(r => Object.fromEntries(header.map((h, j) => [h, (r[j] ?? '').trim()])));
  return { header, items };
}

const quote = v => (/[",\n\r]/.test(v) ? `"${v.replace(/"/g, '""')}"` : v);
export function toCSV(items, columns) {
  const lines = [columns.join(',')];
  for (const it of items) lines.push(columns.map(c => quote(String(it[c] ?? ''))).join(','));
  return lines.join('\n') + '\n';
}

// ---------------------------------------------------------------- GitHub API
function b64decode(b64) {
  const bin = atob(b64.replace(/\s/g, ''));
  return new TextDecoder().decode(Uint8Array.from(bin, ch => ch.charCodeAt(0)));
}
function b64encode(str) {
  const bytes = new TextEncoder().encode(str);
  let bin = '';
  for (let i = 0; i < bytes.length; i += 0x8000) bin += String.fromCharCode(...bytes.subarray(i, i + 0x8000));
  return btoa(bin);
}
async function gh(path, init = {}, settings = getSettings()) {
  return fetch(API + path, {
    ...init,
    cache: 'no-store',
    headers: {
      Accept: 'application/vnd.github+json',
      'X-GitHub-Api-Version': '2022-11-28',
      Authorization: `Bearer ${settings.token}`,
      ...(init.body ? { 'Content-Type': 'application/json' } : {}),
    },
  });
}
async function errorText(res) {
  try { const b = await res.json(); return `${res.status}: ${b.message || res.statusText}`; }
  catch { return `${res.status}: ${res.statusText}`; }
}
function filePath(name, s = getSettings()) {
  return `/repos/${s.owner}/${s.repo}/contents/${s.dataDir || 'data'}/${name}.csv`;
}

/** Check that the token can write to the repo. Resolves to the repo's full name or throws. */
export async function testConnection(s) {
  const res = await gh(`/repos/${s.owner}/${s.repo}`, {}, s);
  if (res.status === 401) throw new Error('GitHub rejected the token (expired or mistyped).');
  if (res.status === 404) throw new Error('Repository not found, or the token has no access to it.');
  if (!res.ok) throw new Error(await errorText(res));
  const repo = await res.json();
  if (repo.permissions && !repo.permissions.push) throw new Error('The token can read but not write. Give it "Contents: Read and write".');
  return repo.full_name;
}

async function fetchRemote(name) {
  const s = getSettings();
  const res = await gh(`${filePath(name, s)}?ref=${encodeURIComponent(s.branch || 'main')}`);
  if (res.status === 404) return { header: COLUMNS[name], items: [], sha: null };
  if (!res.ok) throw new Error(await errorText(res));
  const body = await res.json();
  return { ...toObjects(parseCSV(b64decode(body.content))), sha: body.sha };
}

// ---------------------------------------------------------------- cache, queue, optimistic view
export function cached(name) { return lsGet(K.table(name), null); }
export function queue(name) { return lsGet(K.queue(name), []); }
export function pendingCount() { return Object.keys(COLUMNS).reduce((n, t) => n + queue(t).length, 0); }

function applyOps(items, ops) {
  const out = items.map(x => ({ ...x }));
  for (const op of ops) {
    const i = out.findIndex(x => x.id === op.id);
    if (op.op === 'delete') { if (i >= 0) out.splice(i, 1); }
    else if (i >= 0) out[i] = { ...out[i], ...op.row };
    else out.push({ ...op.row });
  }
  return out;
}

/** Current rows as the owner sees them: the last fetched file plus changes not yet pushed. */
export function rows(name) {
  const c = cached(name);
  const ops = queue(name);
  const pending = new Set(ops.map(o => o.id));
  return applyOps(c ? c.items : [], ops).map(x => ({ ...x, _pending: pending.has(x.id) }));
}
export function hasData(name) { return !!cached(name) || queue(name).length > 0; }

function clean(name, row) {
  const out = {};
  for (const c of COLUMNS[name]) out[c] = row[c] == null ? '' : String(row[c]).trim();
  return out;
}
export function upsert(name, row) {
  const q = queue(name);
  q.push({ op: 'upsert', id: row.id, row: clean(name, row), at: Date.now() });
  lsSet(K.queue(name), q);
  emit();
  scheduleSync(name);
}
export function remove(name, id) {
  const q = queue(name);
  q.push({ op: 'delete', id, at: Date.now() });
  lsSet(K.queue(name), q);
  emit();
  scheduleSync(name);
}

// ---------------------------------------------------------------- ids
const ALPHABET = 'abcdefghijkmnopqrstuvwxyz23456789';
export function rand(n = 4) {
  return Array.from(crypto.getRandomValues(new Uint8Array(n)), b => ALPHABET[b % ALPHABET.length]).join('');
}
export function slug(text) {
  return (text || '').normalize('NFKD').replace(/[̀-ͯ]/g, '').toLowerCase()
    .replace(/[^a-z0-9]+/g, '-').replace(/^-+|-+$/g, '') || 'place';
}

// ---------------------------------------------------------------- status and sync
const state = {};    // table → { state: 'idle'|'syncing'|'error'|'offline', error }
const running = {};
const timers = {};
function setState(name, s, error = '') { state[name] = { state: s, error }; emit(); }

export function overallStatus() {
  const all = Object.keys(COLUMNS).map(n => state[n]?.state || 'idle');
  const pending = pendingCount();
  const err = Object.values(state).find(s => s.state === 'error');
  if (all.includes('syncing')) return { state: 'syncing', label: 'Saving…', pending };
  if (err) return { state: 'error', label: 'Sync error', pending, error: err.error };
  if (all.includes('offline') && pending) return { state: 'offline', label: `Offline · ${pending} waiting`, pending };
  if (pending) return { state: 'pending', label: `${pending} waiting`, pending };
  return { state: 'idle', label: 'Synced', pending };
}

function scheduleSync(name, delay = 600) {
  clearTimeout(timers[name]);
  timers[name] = setTimeout(() => { sync(name).catch(() => {}); }, delay);
}

function summary(name, ops) {
  const adds = ops.filter(o => o.op === 'upsert').length;
  const dels = ops.length - adds;
  const parts = [adds && `${adds} saved`, dels && `${dels} deleted`].filter(Boolean);
  return `${name}: ${parts.join(', ')} (from the dashboard)`;
}

/** Push queued changes for one table. Re-reads the file first, so edits made elsewhere survive. */
export async function sync(name) {
  if (!isOwner()) return;
  if (running[name]) { scheduleSync(name, 1500); return running[name]; }
  const ops = queue(name);
  if (!ops.length) return refresh(name);
  running[name] = (async () => {
    setState(name, 'syncing');
    try {
      const s = getSettings();
      for (let attempt = 0; attempt < 3; attempt++) {
        const remote = await fetchRemote(name);
        const merged = applyOps(remote.items, ops);
        const columns = [...COLUMNS[name], ...remote.header.filter(h => h && !COLUMNS[name].includes(h))];
        const res = await gh(filePath(name, s), {
          method: 'PUT',
          body: JSON.stringify({
            message: summary(name, ops),
            content: b64encode(toCSV(merged, columns)),
            branch: s.branch || 'main',
            ...(remote.sha ? { sha: remote.sha } : {}),
          }),
        });
        if (res.status === 409 || res.status === 422) continue;   // the file changed meanwhile: retry
        if (!res.ok) throw new Error(await errorText(res));
        const body = await res.json();
        lsSet(K.queue(name), queue(name).slice(ops.length));    // keep changes made while saving
        lsSet(K.table(name), { items: merged, header: columns, sha: body.content.sha, at: Date.now() });
        setState(name, 'idle');
        if (queue(name).length) scheduleSync(name);
        return;
      }
      throw new Error('The file kept changing on GitHub while saving. Try again.');
    } catch (e) {
      const offline = navigator.onLine === false || e instanceof TypeError;
      setState(name, offline ? 'offline' : 'error', offline ? 'No connection' : e.message);
      throw e;
    } finally {
      running[name] = null;
    }
  })();
  return running[name];
}

/** Re-read a table from GitHub (owner only). Keeps the cached copy if offline. */
export async function refresh(name) {
  if (!isOwner()) return;
  try {
    const remote = await fetchRemote(name);
    lsSet(K.table(name), { ...remote, at: Date.now() });
    if (state[name]?.state !== 'syncing') setState(name, 'idle');
    else emit();
  } catch (e) {
    const offline = navigator.onLine === false || e instanceof TypeError;
    setState(name, offline ? 'offline' : 'error', offline ? 'No connection' : e.message);
  }
}

export async function syncAll(names = Object.keys(COLUMNS)) {
  await Promise.allSettled(names.map(n => (queue(n).length ? sync(n) : refresh(n))));
}

if (typeof window !== 'undefined') {
  window.addEventListener('online', () => { if (isOwner()) syncAll(); });
  document.addEventListener('visibilitychange', () => {
    if (document.visibilityState === 'visible' && isOwner() && pendingCount()) syncAll();
  });
}
