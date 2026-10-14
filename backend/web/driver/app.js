'use strict';
const $ = id => document.getElementById(id);
const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[c]));
const T = {
  bn: {title: 'চালক', lang: 'English', code: 'ডিসপ্যাচারের দেওয়া ৬ সংখ্যার কোড', pasteTok: 'কোডের বদলে টোকেন দিন', token: 'অ্যাক্সেস টোকেন',
    login: 'প্রবেশ', logout: 'বের হন', logoutQ: 'বের হবেন? আবার প্রবেশ করতে ডিসপ্যাচারের কাছ থেকে নতুন কোড লাগবে।', refresh: 'রিফ্রেশ',
    none: 'কোনো মিশন নেই', mission: 'বর্তমান মিশন', status: 'অবস্থা', pickup: 'পিকআপ', navigate: 'নেভিগেট', next: 'পরবর্তী ধাপ', noNext: 'আর কোনো ধাপ নেই',
    confirm: 'নিশ্চিত করুন', yes: 'হ্যাঁ', no: 'না', ok: 'অবস্থা আপডেট হয়েছে', sending: 'পাঠানো হচ্ছে…', pairing: 'কোড যাচাই হচ্ছে…',
    newM: 'নতুন মিশন', accept: 'গ্রহণ করুন', eAck: 'গ্রহণ পাঠানো যায়নি। আবার চেষ্টা করুন।', alertsOn: 'মিশন সতর্কতা চালু করুন (শব্দ ও নোটিফিকেশন)',
    cancelled: 'ডিসপ্যাচার মিশনটি বাতিল করেছেন', completed: 'মিশন সম্পন্ন',
    e401: 'প্রবেশ বাতিল বা মেয়াদ শেষ। ডিসপ্যাচারের কাছ থেকে নতুন ৬ সংখ্যার কোড নিয়ে আবার প্রবেশ করুন।', e409: 'মিশন বদলে গেছে। রিফ্রেশ করুন।',
    e429: 'অনুরোধ খুব দ্রুত। একটু পরে চেষ্টা করুন।', eCode: 'কোডটি ভুল বা মেয়াদোত্তীর্ণ। ডিসপ্যাচারের কাছ থেকে নতুন কোড নিন।', eCode6: '৬ সংখ্যার কোড দিন।',
    eCode429: 'অনেকবার ভুল কোড। ১০ মিনিট পরে আবার চেষ্টা করুন।',
    offline: 'অফলাইন। অবস্থা পরিবর্তন করা যাবে না। লোকেশন সর্বোচ্চ ৫ মিনিট রাখা হয় এবং অনলাইন হলে পাঠানো হবে।', eStatus: 'অবস্থা পরিবর্তন ব্যর্থ। আবার চেষ্টা করুন।',
    eNet: 'সার্ভারে পৌঁছানো যায়নি।', slow: 'নেটওয়ার্ক ধীর। আবার চেষ্টা করা হচ্ছে…',
    skew: 'ফোনের ঘড়ি ১ মিনিটের বেশি ভুল। সেটিংসে স্বয়ংক্রিয় তারিখ ও সময় চালু করুন। ট্র্যাকিং চলছে।',
    noVeh: 'এই মিশনে কোনো অ্যাম্বুলেন্স যুক্ত নেই, তাই লোকেশন পাঠানো হচ্ছে না। ডিসপ্যাচারকে ফোন করুন।',
    gpsDenied: 'জিপিএস অনুমতি নেই। ব্রাউজার সেটিংসে অনুমতি দিন।', gpsOff: 'জিপিএস পাওয়া যাচ্ছে না।', gpsNo: 'এই ডিভাইসে জিপিএস নেই।',
    queued: 'সংরক্ষিত লোকেশন (সর্বোচ্চ ৫ মিনিট রাখা হয়)', expSoon: 'আপনার প্রবেশের মেয়াদ ৭ দিনের মধ্যে শেষ হবে। ডিসপ্যাচারের কাছ থেকে নতুন কোড নিন।',
    shiftOn: 'ডিউটি শুরু (মিশনের অ্যালার্ম, প্রতি মিনিটে লোকেশন)', shiftOff: 'ডিউটি শেষ',
    onShift: 'ডিউটিতে আছেন: ফোন পকেটে থাকলেও নতুন মিশনে অ্যালার্ম বাজবে। মিশন ছাড়া প্রতি মিনিটে লোকেশন যায়।',
    shiftFail: 'ডিউটি চালু হয়নি: অ্যাপকে লোকেশনের অনুমতি দিন।'},
  en: {title: 'Driver', lang: 'বাংলা', code: '6-digit code from the dispatcher', pasteTok: 'Use a token instead', token: 'Access token',
    login: 'Sign in', logout: 'Sign out', logoutQ: 'Sign out? You will need a new code from the dispatcher to sign in again.', refresh: 'Refresh',
    none: 'No mission', mission: 'Current mission', status: 'Status', pickup: 'Pickup', navigate: 'Navigate', next: 'Next step', noNext: 'No further steps',
    confirm: 'Confirm', yes: 'Yes', no: 'No', ok: 'Status updated', sending: 'Sending…', pairing: 'Checking code…',
    newM: 'New mission', accept: 'Accept', eAck: 'Could not accept. Try again.', alertsOn: 'Turn on mission alerts (sound and notification)',
    cancelled: 'Cancelled by dispatcher', completed: 'Mission completed',
    e401: 'Signed out: sign-in expired or revoked. Get a new 6-digit code from the dispatcher and sign in again.', e409: 'Mission changed. Refresh.',
    e429: 'Too many requests. Try again shortly.', eCode: 'Wrong or expired code. Ask the dispatcher for a new one.', eCode6: 'Enter the 6-digit code.',
    eCode429: 'Too many wrong codes. Try again in 10 minutes.',
    offline: 'Offline. Status changes unavailable. Locations are kept for up to 5 minutes and sent when back online.', eStatus: 'Status change failed. Try again.',
    eNet: 'Cannot reach server.', slow: 'Network slow, retrying…',
    skew: 'Phone clock is off by more than 1 minute. Turn on automatic date and time in Settings. Tracking still works.',
    noVeh: 'No ambulance is linked to this mission, so your location is not being sent. Call the dispatcher.',
    gpsDenied: 'GPS permission denied. Allow location in browser settings.', gpsOff: 'GPS unavailable.', gpsNo: 'No GPS on this device.',
    queued: 'Saved locations (kept up to 5 minutes)', expSoon: 'Your sign-in expires within 7 days. Ask the dispatcher for a new code.',
    shiftOn: 'Start shift (mission alarm, location every minute)', shiftOff: 'End shift',
    onShift: 'On shift: a new mission rings even with the phone in your pocket. Between missions your location is sent once a minute.',
    shiftFail: 'Shift not running: allow location for the app.'},
};
const SL = {
  bn: {DISPATCHED: 'প্রেরিত', EN_ROUTE_PICKUP: 'পিকআপের পথে', AT_SCENE: 'ঘটনাস্থলে', TRANSPORTING_PATIENT: 'রোগী নিয়ে যাচ্ছি', AT_HOSPITAL: 'হাসপাতালে পৌঁছেছি', COMPLETED: 'সম্পন্ন', CANCELLED: 'বাতিল'},
  en: {DISPATCHED: 'Dispatched', EN_ROUTE_PICKUP: 'En route to pickup', AT_SCENE: 'At scene', TRANSPORTING_PATIENT: 'Transporting patient', AT_HOSPITAL: 'At hospital', COMPLETED: 'Completed', CANCELLED: 'Cancelled'},
};
const DONE = ['COMPLETED', 'CANCELLED'];
const QK = 'driver_ping_queue', QMAX = 200, PING_MS = 5000, STALE_MS = 300000, TIMEOUT_MS = 10000, TITLE = document.title;
let lang = 'bn', token = '', me = null, mission = null, trans = {}, msgs = {}, watchId = null, lastPing = 0, replaying = false;
let audio = null, alertTimer = null, alertN = 0, notified = '', wake = null, nativeKey = null, shift = false;
const t = k => T[lang][k] || k;
const sl = s => Object.hasOwn(SL[lang], s) ? SL[lang][s] : esc(s); // unknown state: escaped raw string
const sleep = ms => new Promise(f => setTimeout(f, ms));
try { token = localStorage.getItem('tok') || ''; lang = localStorage.getItem('lang') || 'bn'; shift = localStorage.getItem('shift') === '1'; } catch (e) {}
function setToken(v) { token = v; try { if (v) localStorage.setItem('tok', v); else localStorage.removeItem('tok'); } catch (e) {} } // localStorage: survives closing the installed app

function say(key, text, err) { // one message slot per key, rendered in the aria-live region
  if (text) msgs[key] = {text, err}; else delete msgs[key];
  $('status').innerHTML = Object.values(msgs).map(m => `<div class="${m.err ? 'err' : ''}">${esc(m.text)}</div>`).join(''); // safe-html: esc() escapes every interpolated value
}
let msgKeys = {}; // key -> translation key, so a language toggle re-renders messages
function sayT(key, tk, err) { msgKeys[key] = tk; say(key, tk ? t(tk) : '', err); }
function retext() { for (const [k, tk] of Object.entries(msgKeys)) if (msgs[k]) say(k, t(tk), msgs[k].err); }

async function fetchT(path, opt) { // every request gives up after 10 s, so a connected-but-dead network never hangs silently
  const c = new AbortController(), tm = setTimeout(() => c.abort(), TIMEOUT_MS);
  try { const r = await fetch(path, {...opt, signal: c.signal}); sayT('slow', ''); return r; }
  catch (e) { if (e.name === 'AbortError') sayT('slow', 'slow', true); throw e; }
  finally { clearTimeout(tm); }
}
const req = (method, body, headers = {}) => ({method, headers: body ? {...headers, 'Content-Type': 'application/json'} : headers, body: body ? JSON.stringify(body) : undefined});
async function api(method, path, body) {
  const tk = token, r = await fetchT(path, req(method, body, {Authorization: 'Bearer ' + tk}));
  if (r.status === 401 && tk === token) signOut(true); // a reply to an older token must not sign out a fresh pairing
  return r;
}
function signOut(expired) { // expired (401): keep the queue, its entries carry their own mission and vehicle
  if (!expired) { shift = false; try { localStorage.removeItem(QK); localStorage.removeItem('shift'); } catch (e) {} } // a new sign-in starts off shift
  setToken(''); me = null; mission = null; msgs = {}; msgKeys = {};
  track(); render(); if (expired) sayT('auth', 'e401', true);
}
async function pair(code) {
  sayT('auth', 'pairing');
  try {
    const r = await fetchT('/pair', req('POST', {code}));
    if (r.ok) { setToken((await r.json()).token); sayT('auth', ''); return load(); }
    sayT('auth', {401: 'eCode', 422: 'eCode6', 429: 'eCode429'}[r.status] || 'eNet', true);
  } catch (e) { sayT('auth', navigator.onLine ? 'eNet' : 'offline', true); }
}
function fromHash() { // the console's QR opens /driver/#pair=CODE; the code leaves the address bar and history at once
  const m = /^#pair=(.+)$/.exec(location.hash);
  if (!m) return false;
  history.replaceState(null, '', location.pathname + location.search); pair(m[1]); return true;
}

// ---- offline queue (pings only; status changes are never queued). Each entry keeps its vehicle and mission (B9).
function qGet() { try { return JSON.parse(localStorage.getItem(QK) || '[]'); } catch (e) { return []; } }
function qSet(a) { try { localStorage.setItem(QK, JSON.stringify(a.slice(-QMAX))); } catch (e) {} }
function qAdd(p) { qSet(qGet().concat(p)); }
const qOk = p => !!(me && active() && p.vehicle_id === me.vehicle_id && p.mission_id === mission.mission_id && Date.now() - Date.parse(p.ts) < STALE_MS);
async function replay() {
  if (replaying || !navigator.onLine) return;
  replaying = true;
  try {
    for (;;) {
      const q = qGet().filter(qOk); qSet(q); // other missions' and stale entries go
      if (!q.length) break;
      const r = await postPing(q[0]);
      if (r.status === 401 || r.status >= 500) break;
      if (r.status !== 429) qSet(qGet().slice(1)); // sent, or refused for good (4xx): drop; new entries only append
      await sleep(1100); // server limit: 1 ping/s/vehicle
    }
  } catch (e) {} finally { replaying = false; }
}
async function postPing(p) { // sent_at lets the server age a queued fix whatever the phone clock says
  const r = await api('POST', `/vehicles/${encodeURIComponent(p.vehicle_id)}/pings`, {lat: p.lat, lng: p.lng, accuracy: p.accuracy, ts: p.ts, sent_at: new Date().toISOString()});
  if (r.ok) { const j = await r.json().catch(() => ({})); sayT('skew', Math.abs(j.clock_skew_s) > 60 ? 'skew' : '', true); } // B4
  return r;
}

// ---- GPS (web path; the native wrapper pings on its own)
function onPos(pos) {
  sayT('gps', '');
  const now = Date.now();
  if (!me || !me.vehicle_id || !active() || now - lastPing < PING_MS) return;
  lastPing = now;
  sendPing({lat: pos.coords.latitude, lng: pos.coords.longitude, accuracy: Math.min(pos.coords.accuracy, 1e5), ts: new Date(now).toISOString(),
    vehicle_id: me.vehicle_id, mission_id: mission.mission_id});
}
async function sendPing(p) {
  if (!navigator.onLine) { qAdd(p); return; }
  try {
    const r = await postPing(p);
    sayT('rate', r.status === 429 ? 'e429' : '', true);
    if (r.ok) replay(); else if (r.status >= 500) qAdd(p);
  } catch (e) { qAdd(p); }
}
function onGpsErr(e) { sayT('gps', e.code === 1 ? 'gpsDenied' : 'gpsOff', true); }
function startGps() {
  if (watchId !== null) return;
  if (!navigator.geolocation) return sayT('gps', 'gpsNo', true);
  watchId = navigator.geolocation.watchPosition(onPos, onGpsErr, {enableHighAccuracy: true, maximumAge: 5000, timeout: 20000});
}
function stopGps() { if (watchId !== null) navigator.geolocation.clearWatch(watchId); watchId = null; sayT('gps', ''); }
const active = () => !!mission && !DONE.includes(mission.status);

// ---- what a live mission needs: tracking (web or native), screen on, alert until accepted
// On shift (Android wrapper only): between missions its service reports the paired vehicle and rings for new missions.
const onShift = () => shift && !!window.AmbulanceNative && !!me?.paired_vehicle_id;
function track() {
  const live = !!token && active(), on = live && !!me.vehicle_id, idle = !!token && !live && onShift();
  sayT('veh', live && !on ? 'noVeh' : '', true); // B7: never ping /vehicles/null
  keepAwake(live); alerting(live && !mission.acknowledged_at);
  const nat = nativeTrack(on || idle, live);
  sayT('shift', onShift() ? (nat ? 'onShift' : 'shiftFail') : '', !nat);
  if (nat) stopGps(); // the wrapper's service pings, so the web watch stays off and the server never gets both
  else if (on) { startGps(); replay(); } else stopGps();
}
function nativeTrack(on, live) { // Android wrapper; isTracking() is the truth, since its service can stop itself
  const N = window.AmbulanceNative;
  if (!N) return false;
  try {
    if (!on) { if (N.isTracking()) N.stopTracking(); nativeKey = ''; return false; }
    const k = JSON.stringify({baseUrl: location.origin, token, vehicleId: live ? me.vehicle_id : me.paired_vehicle_id,
      missionId: live ? mission.mission_id : '', shift: onShift()});
    if (N.isTracking() && (nativeKey === null || nativeKey === k)) { nativeKey = k; return true; } // first load: adopt it
    // N3: a service started from the background gets no location, and neither would a hidden page's web watch. Wait:
    // visibilitychange calls track() again when the driver is back.
    if (document.visibilityState !== 'visible') return true;
    nativeKey = N.startTracking(k) === true ? k : ''; // false (e.g. baseUrl refused): the web path takes over
    return !!nativeKey;
  } catch (e) { return false; }
}
function setShift(v) { shift = v; try { localStorage.setItem('shift', v ? '1' : ''); } catch (e) {} track(); render(); }
function keepAwake(on) { // the browser drops the lock whenever the page is hidden, so visibilitychange asks again
  if (on && !wake && navigator.wakeLock && document.visibilityState === 'visible') {
    const p = wake = navigator.wakeLock.request('screen').then(s => { s.onrelease = () => { if (wake === p) wake = null; }; return s; },
      () => { if (wake === p) wake = null; return null; });
  } else if (!on && wake) { const p = wake; wake = null; p.then(s => s && s.release()).catch(() => {}); }
}
function armAudio() { try { audio = audio || new AudioContext(); audio.resume().catch(() => {}); } catch (e) {} } // sound needs a tap first
function siren() {
  if (!audio || audio.state !== 'running') return;
  const o = audio.createOscillator(), g = audio.createGain(), n = audio.currentTime;
  o.type = 'square'; o.frequency.setValueAtTime(880, n); o.frequency.setValueAtTime(660, n + 0.3);
  g.gain.value = 0.2; o.connect(g).connect(audio.destination); o.start(n); o.stop(n + 0.6);
}
async function notify() {
  const o = {body: mission.pickup_address, tag: 'mission', requireInteraction: true};
  try { const reg = await navigator.serviceWorker?.getRegistration(); if (reg) await reg.showNotification(t('newM'), o); else new Notification(t('newM'), o); } catch (e) {}
}
function alerting(on) { // until Accept: flashing title, siren and vibration every 3 s, one notification
  if (!on) { clearInterval(alertTimer); alertTimer = null; document.title = TITLE; return; }
  if (!alertTimer) { alertN = 0; alertTimer = setInterval(alertTick, 1000); alertTick(); }
}
function alertTick() {
  document.title = alertN % 2 ? TITLE : `*** ${t('newM')} ***`;
  if (alertN++ % 3 === 0) {
    siren();
    if (navigator.userActivation?.hasBeenActive ?? true) try { navigator.vibrate?.([400, 200, 400]); } catch (e) {} // before a tap Chrome blocks it with a console error
  }
  if (notified !== mission.mission_id && window.Notification?.permission === 'granted') { notified = mission.mission_id; notify(); }
}
const alertsOff = () => !audio || window.Notification?.permission === 'default';
async function enableAlerts() {
  armAudio();
  if (window.Notification?.permission === 'default') try { await Notification.requestPermission(); } catch (e) {}
  render();
}

// ---- data
async function load() {
  if (!token) return;
  try {
    const r = await api('GET', '/me'); if (!r.ok) return; // every load: the vehicle can change between missions
    me = await r.json();
    const m = await api('GET', '/missions/current'); // also a mission that ended in the last 10 min (B15)
    if (m.status === 404) mission = null; else if (m.ok) mission = await m.json(); else return;
    track(); // right after mission changes: the alert timer reads it
    if (!Object.keys(trans).length) { const tr = await api('GET', '/meta/transitions'); if (tr.ok) trans = await tr.json(); } // fixed per role
    sayT('net', '');
    sayT('exp', Date.parse(me.token_expires_at) - Date.now() < 7 * 864e5 ? 'expSoon' : '', true);
  } catch (e) { if (e.name !== 'AbortError') sayT('net', navigator.onLine ? 'eNet' : 'offline', true); }
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
  sayT('act', 'sending');
  try {
    const r = await api('PATCH', `/missions/${encodeURIComponent(mission.mission_id)}/status`, {status: s});
    if (r.status === 401) return;
    if (r.status === 409) { sayT('act', 'e409', true); return load(); }
    if (r.status === 429) return sayT('act', 'e429', true);
    if (!r.ok) return sayT('act', 'eStatus', true);
    sayT('act', 'ok'); await load();
  } catch (e) { sayT('act', 'eStatus', true); }
}
async function accept() {
  try {
    const r = await api('POST', `/missions/${encodeURIComponent(mission.mission_id)}/ack`);
    sayT('act', r.ok || r.status === 401 || r.status === 409 ? '' : 'eAck', true);
    if (r.ok) { mission = await r.json(); track(); render(); } // stop the alert now, not after the reload
  } catch (e) { sayT('act', 'eAck', true); }
  load();
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
    a.innerHTML = `<form id="f"><label for="code">${esc(t('code'))}</label><input id="code" inputmode="numeric" autocomplete="one-time-code" required><button class="big">${esc(t('login'))}</button></form><details><summary>${esc(t('pasteTok'))}</summary><form id="ft"><label for="tk">${esc(t('token'))}</label><input id="tk" type="password" autocomplete="off" required><button class="big sec">${esc(t('login'))}</button></form></details>`; // safe-html: only esc()-ed static i18n strings
    $('f').onsubmit = e => { e.preventDefault(); pair($('code').value.replace(/[\s-]/g, '')); };
    $('ft').onsubmit = e => { e.preventDefault(); setToken($('tk').value.trim()); sayT('auth', ''); load(); };
    return;
  }
  const q = qGet().filter(qOk).length;
  let h = alertsOff() ? `<button class="big sec" id="al">${esc(t('alertsOn'))}</button>` : '';
  if (window.AmbulanceNative && me?.paired_vehicle_id) h += `<button class="big${shift ? ' sec' : ''}" id="shift">${esc(t(shift ? 'shiftOff' : 'shiftOn'))}</button>`;
  if (!mission) h += `<div class="card">${esc(t('none'))}</div>`;
  else {
    const id = `#<span title="${esc(mission.mission_id)}">${esc(mission.mission_id.slice(0, 8))}</span>`;
    const pick = `<p>${esc(t('pickup'))}: ${esc(mission.pickup_address)}</p>`;
    if (!active()) h += `<div class="card ended"><h2>${esc(t(mission.status === 'CANCELLED' ? 'cancelled' : 'completed'))}</h2><p>${id}</p>${pick}</div>`;
    else if (!mission.acknowledged_at) h += `<div class="card new"><h2>${esc(t('newM'))} ${id}</h2>${pick}${navLink(mission)}</div><button class="big" id="ack">${esc(t('accept'))}</button>`;
    else {
      const nx = trans[mission.status] || [];
      h += `<div class="card"><h2>${esc(t('mission'))} ${id}</h2><p>${esc(t('status'))}: <span class="badge">${sl(mission.status)}</span></p>${pick}${navLink(mission)}</div>
        <h3>${esc(t('next'))}</h3>` + (nx.length ? nx.map(s => `<button class="big" data-s="${esc(s)}">${sl(s)}</button>`).join('') : `<p>${esc(t('noNext'))}</p>`);
    }
  }
  if (q) h += `<p>${esc(t('queued'))}: ${q}</p>`;
  h += `<button class="sec" id="rf">${esc(t('refresh'))}</button> <button class="sec" id="lo">${esc(t('logout'))}</button>`;
  a.innerHTML = h;
  a.querySelectorAll('[data-s]').forEach(b => b.onclick = () => setStatus(b.dataset.s));
  if ($('al')) $('al').onclick = enableAlerts;
  if ($('ack')) $('ack').onclick = accept;
  if ($('shift')) $('shift').onclick = () => setShift(!shift);
  $('rf').onclick = () => { sayT('act', ''); load(); };
  $('lo').onclick = async () => { if (await confirmDlg(esc(t('logoutQ')))) signOut(false); };
}

$('lang').onclick = () => { lang = lang === 'bn' ? 'en' : 'bn'; try { localStorage.setItem('lang', lang); } catch (e) {} retext(); render(); };
addEventListener('online', () => { sayT('net', ''); load(); }); // load() replays once me and mission are fresh (B9)
addEventListener('offline', () => sayT('net', 'offline', true));
addEventListener('hashchange', fromHash);
addEventListener('ambulance-native-stopped', () => load()); // 401: /me answers 401 and routes to re-pairing; 403/404: shows the ended mission
addEventListener('pointerdown', armAudio);
document.addEventListener('visibilitychange', () => { if (me) track(); }); // screen wake lock, and native start on return (N3)
setInterval(() => { if (token && navigator.onLine) load(); }, 15000);
if ('serviceWorker' in navigator) navigator.serviceWorker.register('sw.js').catch(() => {});
render(); if (!navigator.onLine) sayT('net', 'offline', true); if (!fromHash()) load();
