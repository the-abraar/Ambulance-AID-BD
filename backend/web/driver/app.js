'use strict';
const $ = id => document.getElementById(id);
const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[c]));
const T = {
  bn: {title: 'চালক', lang: 'English', token: 'অ্যাক্সেস টোকেন', login: 'প্রবেশ', logout: 'বের হন', refresh: 'রিফ্রেশ',
    none: 'কোনো মিশন নেই', mission: 'বর্তমান মিশন', status: 'অবস্থা', pickup: 'পিকআপ', navigate: 'নেভিগেট', next: 'পরবর্তী ধাপ', noNext: 'আর কোনো ধাপ নেই',
    confirm: 'নিশ্চিত করুন', yes: 'হ্যাঁ', no: 'না', ok: 'অবস্থা আপডেট হয়েছে',
    e401: 'টোকেন বাতিল বা ভুল। আবার প্রবেশ করুন।', e409: 'মিশন বদলে গেছে। রিফ্রেশ করুন।', e429: 'অনুরোধ খুব দ্রুত। একটু পরে চেষ্টা করুন।',
    offline: 'অফলাইন। অবস্থা পরিবর্তন করা যাবে না; লোকেশন সংরক্ষিত হচ্ছে।', eStatus: 'অবস্থা পরিবর্তন ব্যর্থ। আবার চেষ্টা করুন।', eNet: 'সার্ভারে পৌঁছানো যায়নি।',
    gpsDenied: 'জিপিএস অনুমতি নেই। ব্রাউজার সেটিংসে অনুমতি দিন।', gpsOff: 'জিপিএস পাওয়া যাচ্ছে না।', gpsNo: 'এই ডিভাইসে জিপিএস নেই।', queued: 'সংরক্ষিত পিং'},
  en: {title: 'Driver', lang: 'বাংলা', token: 'Access token', login: 'Sign in', logout: 'Sign out', refresh: 'Refresh',
    none: 'No mission', mission: 'Current mission', status: 'Status', pickup: 'Pickup', navigate: 'Navigate', next: 'Next step', noNext: 'No further steps',
    confirm: 'Confirm', yes: 'Yes', no: 'No', ok: 'Status updated',
    e401: 'Token invalid or revoked. Sign in again.', e409: 'Mission changed. Refresh.', e429: 'Too many requests. Try again shortly.',
    offline: 'Offline. Status changes unavailable; locations are being saved.', eStatus: 'Status change failed. Try again.', eNet: 'Cannot reach server.',
    gpsDenied: 'GPS permission denied. Allow location in browser settings.', gpsOff: 'GPS unavailable.', gpsNo: 'No GPS on this device.', queued: 'Queued pings'},
};
const SL = {
  bn: {DISPATCHED: 'প্রেরিত', EN_ROUTE_PICKUP: 'পিকআপের পথে', AT_SCENE: 'ঘটনাস্থলে', TRANSPORTING_PATIENT: 'রোগী নিয়ে যাচ্ছি', AT_HOSPITAL: 'হাসপাতালে পৌঁছেছি', COMPLETED: 'সম্পন্ন', CANCELLED: 'বাতিল'},
  en: {DISPATCHED: 'Dispatched', EN_ROUTE_PICKUP: 'En route to pickup', AT_SCENE: 'At scene', TRANSPORTING_PATIENT: 'Transporting patient', AT_HOSPITAL: 'At hospital', COMPLETED: 'Completed', CANCELLED: 'Cancelled'},
};
const DONE = ['COMPLETED', 'CANCELLED'];
const QK = 'driver_ping_queue', QMAX = 200, PING_MS = 5000, STALE_MS = 300000;
let lang = 'bn', token = '', me = null, mission = null, trans = {}, msgs = {}, watchId = null, lastPing = 0, replaying = false;
const t = k => T[lang][k] || k;
const sl = s => Object.hasOwn(SL[lang], s) ? SL[lang][s] : esc(s); // unknown state: escaped raw string
try { token = sessionStorage.getItem('tok') || ''; lang = localStorage.getItem('lang') || 'bn'; } catch (e) {}

function say(key, text, err) { // one message slot per key, rendered in the aria-live region
  if (text) msgs[key] = {text, err}; else delete msgs[key];
  $('status').innerHTML = Object.values(msgs).map(m => `<div class="${m.err ? 'err' : ''}">${esc(m.text)}</div>`).join(''); // safe-html: esc() escapes every interpolated value
}
let msgKeys = {}; // key -> translation key, so a language toggle re-renders messages
function sayT(key, tk, err) { msgKeys[key] = tk; say(key, tk ? t(tk) : '', err); }
function retext() { for (const [k, tk] of Object.entries(msgKeys)) if (msgs[k]) say(k, t(tk), msgs[k].err); }

async function api(method, path, body) {
  const r = await fetch(path, {method, headers: {Authorization: 'Bearer ' + token, ...(body ? {'Content-Type': 'application/json'} : {})}, body: body ? JSON.stringify(body) : undefined});
  if (r.status === 401) { signOut(true); }
  return r;
}
function signOut(expired) {
  token = ''; me = null; mission = null; stopGps();
  try { sessionStorage.removeItem('tok'); } catch (e) {}
  render(); if (expired) sayT('auth', 'e401', true);
}

// ---- offline queue (pings only; status changes are never queued)
function qGet() { try { return JSON.parse(localStorage.getItem(QK) || '[]'); } catch (e) { return []; } }
function qSet(a) { try { localStorage.setItem(QK, JSON.stringify(a.slice(-QMAX))); } catch (e) {} }
function qAdd(p) { qSet(qGet().concat(p)); }
async function replay() {
  if (replaying || !me || !navigator.onLine) return;
  replaying = true;
  try {
    let q = qGet().filter(p => Date.now() - Date.parse(p.ts) < STALE_MS);
    qSet(q);
    while (q.length) {
      const r = await api('POST', `/vehicles/${encodeURIComponent(me.vehicle_id)}/pings`, q[0]);
      if (r.status === 429) { await new Promise(f => setTimeout(f, 1100)); continue; }
      if (r.status === 401 || r.status >= 500) break;
      q = q.slice(1); qSet(q); // sent, or rejected permanently (4xx): drop
      await new Promise(f => setTimeout(f, 1100)); // server limit: 1 ping/s/vehicle
      q = qGet().filter(p => Date.now() - Date.parse(p.ts) < STALE_MS);
    }
  } catch (e) {} finally { replaying = false; }
}

// ---- GPS
function onPos(pos) {
  sayT('gps', '');
  const now = Date.now();
  if (!me || !active() || now - lastPing < PING_MS) return;
  lastPing = now;
  sendPing({lat: pos.coords.latitude, lng: pos.coords.longitude, ts: new Date(now).toISOString()});
}
async function sendPing(p) {
  if (!navigator.onLine) { qAdd(p); return; }
  try {
    const r = await api('POST', `/vehicles/${encodeURIComponent(me.vehicle_id)}/pings`, p);
    if (r.status === 429) sayT('rate', 'e429', true);
    else { sayT('rate', ''); if (r.ok) replay(); else if (r.status >= 500) qAdd(p); }
  } catch (e) { qAdd(p); }
}
function onGpsErr(e) { sayT('gps', e.code === 1 ? 'gpsDenied' : 'gpsOff', true); }
function startGps() {
  if (watchId !== null) return;
  if (!navigator.geolocation) return sayT('gps', 'gpsNo', true);
  watchId = navigator.geolocation.watchPosition(onPos, onGpsErr, {enableHighAccuracy: true, maximumAge: 5000, timeout: 20000});
}
function stopGps() { if (watchId !== null) navigator.geolocation.clearWatch(watchId); watchId = null; sayT('gps', ''); }
const active = () => mission && !DONE.includes(mission.status);

// ---- data
async function load() {
  if (!token) return;
  try {
    if (!me) {
      const r = await api('GET', '/me'); if (!r.ok) return;
      me = await r.json();
    }
    const m = await api('GET', '/missions/current');
    if (m.status === 404) mission = null; else if (m.ok) mission = await m.json(); else return;
    const tr = await api('GET', '/meta/transitions');
    if (tr.ok) trans = await tr.json();
    sayT('net', '');
  } catch (e) { sayT('net', navigator.onLine ? 'eNet' : 'offline', true); }
  active() ? startGps() : stopGps();
  render();
}

function confirmDlg(label) {
  return new Promise(res => {
    const d = document.createElement('dialog');
    d.setAttribute('aria-label', t('confirm'));
    d.innerHTML = `<p>${esc(t('confirm'))}: <b>${label}</b></p><button class="big" data-v="1">${esc(t('yes'))}</button><button class="big sec" data-v="">${esc(t('no'))}</button>`; // safe-html: label is esc()-ed or a static label, rest via esc()
    d.addEventListener('click', e => { const b = e.target.closest('button'); if (b) { d.close(); res(!!b.dataset.v); } });
    d.addEventListener('cancel', () => res(false));
    d.addEventListener('close', () => d.remove());
    document.body.appendChild(d); d.showModal();
  });
}
async function setStatus(s) {
  if (!await confirmDlg(sl(s))) return;
  if (!navigator.onLine) return sayT('act', 'offline', true);
  try {
    const r = await api('PATCH', `/missions/${encodeURIComponent(mission.mission_id)}/status`, {status: s});
    if (r.status === 401) return;
    if (r.status === 409) { sayT('act', 'e409', true); return load(); }
    if (r.status === 429) return sayT('act', 'e429', true);
    if (!r.ok) return sayT('act', 'eStatus', true);
    sayT('act', 'ok'); await load();
  } catch (e) { sayT('act', 'eStatus', true); }
}

function navLink(m) { // built only from numeric lat/lng, never from strings
  const la = m.pickup_lat, ln = m.pickup_lng;
  if (typeof la !== 'number' || typeof ln !== 'number' || !isFinite(la) || !isFinite(ln)) return '';
  return `<p><a id="nav" class="navlink" href="https://www.google.com/maps/dir/?api=1&destination=${la},${ln}" target="_blank" rel="noopener">${esc(t('navigate'))}</a></p>`;
}

function render() {
  document.documentElement.lang = lang;
  $('title').textContent = t('title'); $('lang').textContent = t('lang');
  const a = $('app');
  if (!token) {
    a.innerHTML = `<form id="f"><label for="tk">${esc(t('token'))}</label><input id="tk" type="password" autocomplete="off" required><button class="big">${esc(t('login'))}</button></form>`; // safe-html: only esc()-ed static i18n strings
    $('f').onsubmit = e => { e.preventDefault(); token = $('tk').value.trim(); try { sessionStorage.setItem('tok', token); } catch (x) {} sayT('auth', ''); load(); };
    return;
  }
  const q = qGet().length;
  let h = '';
  if (!mission) h += `<div class="card">${esc(t('none'))}</div>`;
  else {
    const nx = trans[mission.status] || [];
    h += `<div class="card"><h2>${esc(t('mission'))} #<span title="${esc(mission.mission_id)}">${esc(mission.mission_id.slice(0, 8))}</span></h2>
      <p>${esc(t('status'))}: <span class="badge">${sl(mission.status)}</span></p>
      <p>${esc(t('pickup'))}: ${esc(mission.pickup_address)}</p>${navLink(mission)}</div>
      <h3>${esc(t('next'))}</h3>` +
      (nx.length ? nx.map(s => `<button class="big" data-s="${esc(s)}">${sl(s)}</button>`).join('') : `<p>${esc(t('noNext'))}</p>`);
  }
  if (q) h += `<p>${esc(t('queued'))}: ${q}</p>`;
  h += `<button class="sec" id="rf">${esc(t('refresh'))}</button> <button class="sec" id="lo">${esc(t('logout'))}</button>`;
  a.innerHTML = h;
  a.querySelectorAll('[data-s]').forEach(b => b.onclick = () => setStatus(b.dataset.s));
  $('rf').onclick = () => { sayT('act', ''); load(); };
  $('lo').onclick = () => signOut(false);
}

$('lang').onclick = () => { lang = lang === 'bn' ? 'en' : 'bn'; try { localStorage.setItem('lang', lang); } catch (e) {} retext(); render(); };
addEventListener('online', () => { sayT('net', ''); replay(); load(); });
addEventListener('offline', () => sayT('net', 'offline', true));
setInterval(() => { if (token && navigator.onLine) load(); }, 15000);
if ('serviceWorker' in navigator) navigator.serviceWorker.register('sw.js').catch(() => {});
render(); if (!navigator.onLine) sayT('net', 'offline', true); load();
