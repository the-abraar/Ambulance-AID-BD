"use strict";
// All dynamic text goes through h()/textContent, never innerHTML, so API data cannot inject markup.
const ACK_MS = 120000, PAGE = 25, EXPIRY_WARN_MS = 7 * 86400000, DHAKA_CENTRE = [23.7808, 90.4125];
let token = "", me = null, vehicles = [], drivers = [], missions = [], transitions = {}, behalfMoves = {}, timer = null;
let view = "active", offset = 0, pickup = null, audio = null, cancelling = null, behalf = null;
try { token = sessionStorage.getItem("tok") || ""; } catch (e) { /* storage blocked: token lives in memory only */ }

const $ = (id) => document.getElementById(id);
function h(tag, props, ...kids) {
  const e = document.createElement(tag);
  Object.assign(e, props || {});
  for (const k of kids) e.append(k);
  return e;
}
const td = (text, props) => h("td", { textContent: text, ...props });
const btn = (text, onclick, props) => h("button", { type: "button", textContent: text, onclick, ...props });
function toast(msg) {
  const t = h("div", { className: "toast", textContent: msg });
  $("toasts").append(t);
  setTimeout(() => t.remove(), 8000);
}
async function api(method, path, body) {
  let r;
  try {
    r = await fetch(path, {
      method,
      headers: { Authorization: "Bearer " + token, ...(body ? { "Content-Type": "application/json" } : {}) },
      body: body ? JSON.stringify(body) : undefined,
    });
  } catch (e) { toast("Network error"); throw e; }
  if (!r.ok) {
    let d = ""; try { d = (await r.json()).detail; } catch (e) { /* non-JSON error */ }
    if (typeof d !== "string") d = (d || []).map((x) => x.msg || JSON.stringify(x)).join("; ");
    if (r.status === 409) toast(`409: ${d}. Someone changed it first; the table is refreshed.`);
    else toast(`Error ${r.status}: ${d}`);
    throw new Error(r.status + " " + d);
  }
  return r.status === 204 ? null : r.json();
}
const enc = encodeURIComponent;
const short = (s) => (s ? s.slice(0, 8) : "-");
const nameOf = (list, key, id, f) => { const x = list.find((i) => i[key] === id); return x ? f(x) : short(id); };
const driverName = (id) => (id ? nameOf(drivers, "driver_id", id, (d) => d.name) : "-");
const label = (s) => s.charAt(0) + s.slice(1).toLowerCase().replace(/_/g, " ");
const dz = (v) => v ? v + (v.length === 16 ? ":00" : "") + "+06:00" : null; // datetime-local has no zone: labels say Dhaka time
const BACKFILL = ["EN_ROUTE_PICKUP", "AT_SCENE", "TRANSPORTING_PATIENT", "AT_HOSPITAL"]; // the steps between dispatch and the end
function backfillSteps(f) { // completed: every step (unknown time = null); cancelled: the steps up to the last one with a time
  const at = BACKFILL.map((s) => dz(f["bf_" + s].value)), end = f.bf_end.value;
  const n = end === "COMPLETED" ? at.length : at.reduce((k, x, i) => (x ? i + 1 : k), 0);
  return [...BACKFILL.slice(0, n).map((status, i) => ({ status, at: at[i] })), { status: end, at: dz(f.bf_end_at.value) }];
}

// Dhaka is UTC+6 with no DST. sv-SE gives "2026-10-14 16:05:12"; never the browser's own zone.
const DHAKA = new Intl.DateTimeFormat("sv-SE", { timeZone: "Asia/Dhaka", year: "numeric", month: "2-digit", day: "2-digit",
  hour: "2-digit", minute: "2-digit", second: "2-digit" });
const dhaka = (ts) => (ts ? DHAKA.format(new Date(ts)) : "-");
function dur(ms) {
  const s = Math.max(0, Math.round(ms / 1000)), m = Math.floor(s / 60);
  return m < 60 ? `${m}:${String(s % 60).padStart(2, "0")}` : `${Math.floor(m / 60)} h ${String(m % 60).padStart(2, "0")} min`;
}
const lateAck = (m) => m.status === "DISPATCHED" && !m.acknowledged_at && Date.now() - Date.parse(m.created_at) > ACK_MS;
function driverProblem(d) {
  if (!d) return "no driver: pair one below";
  if (d.revoked) return "driver revoked";
  return Date.parse(d.expires_at) <= Date.now() ? "driver token expired" : "";
}
function keep(sel, opts) { // replace options, keep the user's choice if it is still there and allowed
  const cur = sel.value;
  sel.replaceChildren(...opts);
  sel.value = cur;
  if (!sel.value || sel.selectedOptions[0].disabled) sel.selectedIndex = 0;
}

// Map: OSM tiles (allowed by the CSP's img-src), vehicles and the pickup point as SVG circles.
const map = L.map("map", { center: DHAKA_CENTRE, zoom: 12 });
L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", { maxZoom: 19,
  attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors' }).addTo(map);
const vehLayer = L.layerGroup().addTo(map);
let pickupMark = null;
function setPickup(ll) {
  pickup = ll && { lat: +ll.lat.toFixed(5), lng: +ll.lng.toFixed(5) }; // ~1 m; more digits would be false precision
  if (pickupMark) pickupMark.remove();
  pickupMark = pickup && L.circleMarker(pickup, { radius: 10, className: "pickup", interactive: false }).addTo(map);
  $("pickup").textContent = pickup ? `${pickup.lat}, ${pickup.lng}` : "not set, click the map";
}
map.on("click", (e) => setPickup(e.latlng));
$("centre").onclick = () => setPickup(map.getCenter());

function renderMap() {
  vehLayer.clearLayers();
  for (const v of vehicles) {
    const p = v.last_position;
    if (!v.active || !p) continue;
    const kind = p.stale ? "stale" : v.busy ? "busy" : "free";
    if (p.accuracy != null) L.circle([p.lat, p.lng], { radius: p.accuracy, className: "acc", interactive: false }).addTo(vehLayer);
    L.circleMarker([p.lat, p.lng], { radius: 8, className: "veh veh-" + kind, bubblingMouseEvents: false })
      .bindTooltip(h("span", { textContent: `${v.registration} ${kind}` }), { permanent: true, direction: "right", offset: [8, 0] })
      .on("click", () => { const s = $("newm").elements.veh; s.value = v.vehicle_id; if (!s.value || s.selectedOptions[0].disabled) s.selectedIndex = 0; })
      .addTo(vehLayer);
  }
}
function renderVehicles() {
  fill($("vehicles").tBodies[0], vehicles.map((v) => {
    const p = v.last_position, state = !v.active ? "inactive" : v.busy ? "busy" : "free";
    // Free vehicles report only while their driver is on shift in the Android app, so an old position is red only on a mission.
    const pos = p ? `${p.lat.toFixed(5)}, ${p.lng.toFixed(5)}${p.accuracy != null ? ` ±${Math.round(p.accuracy)} m` : ""} at ${dhaka(p.ts)}${p.stale ? " (STALE)" : ""}`
      : "no position yet";
    return h("tr", {}, td(v.registration), td(v.operator), td(state, { className: "st-" + state }), td(driverName(v.driver_id)),
      td(pos, { className: v.busy && (!p || p.stale) ? "stale" : p && !p.stale ? "fresh" : "" }));
  }));
  keep($("newm").elements.veh, [h("option", { value: "", textContent: "Pick a free vehicle" }),
    ...vehicles.filter((v) => v.active).map((v) => {
      const d = drivers.find((x) => x.driver_id === v.driver_id), why = v.busy ? "busy" : driverProblem(d);
      // a back-fill is already over, so a busy vehicle or a since-revoked driver is fine
      return h("option", { value: v.vehicle_id, disabled: !!why && !$("newm").elements.dispatched.value, textContent: `${v.registration} · ${d ? d.name : "no driver"}${why ? ` (${why})` : ""}` });
    })]);
  keep($("pairf").elements.veh, vehicles.filter((v) => v.active).map((v) => h("option", { value: v.vehicle_id, textContent: v.registration })));
  renderMap();
}
function tokenState(d) {
  const left = Date.parse(d.expires_at) - Date.now();
  if (d.revoked) return "revoked";
  return left <= 0 ? "expired" : `valid until ${dhaka(d.expires_at)}${left < EXPIRY_WARN_MS ? " (expires within 7 days)" : ""}`;
}
function renderDrivers() {
  fill($("drivers").tBodies[0], drivers.map((d) => h("tr", {}, td(d.name), td(d.phone || "-"),
    td(tokenState(d), { className: driverProblem(d) ? "stale" : "" }),
    ...(me.admin ? [h("td", { className: "acts" }, btn("Pairing code", () => pairingCode(d)), btn("Show token", () => showToken(d)),
      btn("Revoke", () => revokeToken(d)))] : []))));
  const soon = drivers.filter((d) => !d.revoked && Date.parse(d.expires_at) - Date.now() < EXPIRY_WARN_MS);
  $("expiring").hidden = !soon.length;
  $("expiring").querySelector("ul").replaceChildren(...soon.map((d) => h("li", { textContent: `${d.name}: ${tokenState(d)}` })));
  keep($("pairf").elements.drv, [h("option", { value: "", textContent: "(nobody: unpair)" }),
    ...drivers.filter((d) => !driverProblem(d)).map((d) => h("option", { value: d.driver_id, textContent: d.name }))]);
}
function renderMissions() {
  fill($("missions").tBodies[0], missions.map((m) => {
    const acts = h("td", { className: "acts" }), end = m.completed_at || m.cancelled_at, late = lateAck(m);
    for (const next of behalfMoves[m.status] || []) acts.append(btn("On behalf: " + label(next), () => openBehalf(m, next)));
    acts.append(btn("Audit", () => showAudit(m)));
    if ((transitions[m.status] || []).includes("CANCELLED")) acts.append(btn("Cancel…", () => openCancel(m), { className: "danger" }));
    return h("tr", { className: late ? "late" : "" }, h("td", {}, h("code", { textContent: short(m.mission_id), title: m.mission_id })),
      td(label(m.status), { title: m.status }), td(m.pickup_address),
      td(m.assigned_vehicle_id ? nameOf(vehicles, "vehicle_id", m.assigned_vehicle_id, (v) => v.registration) : "-"),
      td(driverName(m.assigned_driver_id)), td(dhaka(m.created_at)),
      td(dur((end ? Date.parse(end) : Date.now()) - Date.parse(m.created_at))),
      td(m.acknowledged_at ? dhaka(m.acknowledged_at) : late ? "NOT ACKNOWLEDGED" : m.status === "DISPATCHED" ? "waiting" : "-"), acts);
  }));
  $("older").disabled = missions.length < PAGE;
  $("newer").disabled = offset === 0;
  $("page").textContent = missions.length ? `${offset + 1}-${offset + missions.length}` : "none";
}
function fill(tbody, rows) { tbody.replaceChildren(...rows); }

function beep() {
  const o = audio.createOscillator(), g = audio.createGain();
  o.frequency.value = 880; g.gain.value = 0.3;
  o.connect(g).connect(audio.destination);
  o.start(); o.stop(audio.currentTime + 0.4);
}
function alarm(active) {
  const late = active.filter(lateAck);
  $("alarm").hidden = !late.length;
  $("alarm").textContent = late.length ? `Not acknowledged within 2 minutes: ${late.map((m) => m.pickup_address).join("; ")}. ` +
    `Phone the driver.${audio ? "" : " Turn on the alarm sound (top right) so you hear the next one."}` : "";
  if (late.length && audio) beep(); // repeats on every poll (5 s) until acknowledged, moved on or cancelled
}

async function refresh() {
  if (!token) return;
  try {
    const f = $("filter").value;
    let active;
    [vehicles, drivers, active] = await Promise.all([api("GET", "/vehicles"), api("GET", "/drivers"), api("GET", "/missions?active=true")]);
    renderDrivers(); renderVehicles(); alarm(active);
    missions = view === "active" ? active.filter((m) => !f || m.status === f)
      : await api("GET", `/missions?limit=${PAGE}&offset=${offset}${f ? "&status=" + enc(f) : ""}`);
    renderMissions();
  } catch (e) { /* toast already shown */ }
}
function setView(v, off) {
  view = v; offset = off;
  $("pager").hidden = v !== "history";
  $("tab-active").setAttribute("aria-pressed", String(v === "active"));
  $("tab-history").setAttribute("aria-pressed", String(v === "history"));
  refresh();
}
async function setStatus(m, status, extra) {
  try { await api("PATCH", `/missions/${m.mission_id}/status`, { status, ...extra }); } catch (e) { /* toast shown */ }
  refresh();
}
function openCancel(m) {
  cancelling = m;
  $("cancel-addr").textContent = m.pickup_address;
  $("cancel-dlg").querySelector("form").reset();
  $("cancel-dlg").showModal();
}
function openBehalf(m, next) {
  behalf = { m, next };
  $("behalf-what").textContent = `${label(m.status)} -> ${label(next)} for ${driverName(m.assigned_driver_id)}, pickup ${m.pickup_address}`;
  $("behalf-dlg").querySelector("form").reset();
  $("behalf-dlg").showModal();
}
async function pairingCode(d) {
  try { showPairing(d.name, await api("POST", `/drivers/${enc(d.driver_id)}/pairing-code`)); } catch (e) { /* toast shown */ }
}
function showPairing(name, r) {
  const url = `${location.origin}/driver/#pair=${r.code}`;
  $("pair-name").textContent = name; $("pair-code").textContent = r.code;
  $("pair-url").textContent = url; $("pair-exp").textContent = dhaka(r.expires_at);
  const q = qrcode(0, "M"), cv = $("pair-qr"), ctx = cv.getContext("2d"), s = 6, pad = 4;
  q.addData(url); q.make();
  const n = q.getModuleCount();
  cv.width = cv.height = (n + 2 * pad) * s;
  ctx.fillStyle = "#fff"; ctx.fillRect(0, 0, cv.width, cv.height); ctx.fillStyle = "#000";
  for (let r = 0; r < n; r++) for (let c = 0; c < n; c++) if (q.isDark(r, c)) ctx.fillRect((c + pad) * s, (r + pad) * s, s, s);
  cv.setAttribute("aria-label", "QR code of " + url);
  $("pair-dlg").showModal();
}
async function showToken(d) {
  if (!confirm(`Show a raw token for ${d.name}? It replaces the current one (the driver is signed out) and lasts 90 days ` +
    "in any chat it is pasted into. A pairing code is safer.")) return;
  try {
    const r = await api("POST", `/drivers/${enc(d.driver_id)}/token/rotate`);
    $("newtok").textContent = `New token for ${d.name} (shown once, click to hide; the old one no longer works; expires ${dhaka(r.expires_at)}): ${r.token}`;
    $("newtok").hidden = false;
  } catch (e) { /* toast shown */ }
}
async function revokeToken(d) {
  if (!confirm(`Revoke ${d.name}'s token? The driver is signed out until you issue a pairing code.`)) return;
  try { await api("POST", `/drivers/${enc(d.driver_id)}/token/revoke`); toast(`Token revoked for ${d.name}`); } catch (e) { /* toast shown */ }
  refresh();
}
async function showAudit(m) {
  try {
    const rows = await api("GET", `/missions/${m.mission_id}/audit`);
    $("audit-what").textContent = `${short(m.mission_id)}: ${m.pickup_address} (Dhaka time)`;
    $("audit").replaceChildren(...rows.map((r) => h("li", { textContent: [dhaka(r.ts),
      `${r.from_status ? label(r.from_status) : "(new)"} -> ${label(r.to_status)}`,
      `by ${r.user_id === me.user_id ? "you" : short(r.user_id)}`, r.on_behalf_of && `for driver ${driverName(r.on_behalf_of)}`,
      r.event_time && `happened ${dhaka(r.event_time)}`, r.reason && `reason: ${r.reason}`].filter(Boolean).join(" · ") })));
    $("drawer").hidden = false;
  } catch (e) { /* toast shown */ }
}

async function connect() {
  try {
    me = await api("GET", "/me");
    if (me.role !== "dispatcher") { toast("403: this console needs a dispatcher token"); return; }
    $("who").textContent = me.admin ? "connected (admin)" : "connected (dispatcher)";
    for (const e of document.querySelectorAll(".admin-only")) e.hidden = !me.admin;
    // Fetched once: the rules never change while the page is open.
    [transitions, behalfMoves] = await Promise.all([api("GET", "/meta/transitions"), api("GET", "/meta/transitions?on_behalf=true")]);
    keep($("filter"), [h("option", { value: "", textContent: "All statuses" }),
      ...Object.keys(transitions).map((s) => h("option", { value: s, textContent: label(s) }))]);
    try { sessionStorage.setItem("tok", token); } catch (e) { /* ignore */ }
    clearInterval(timer);
    await refresh();
    timer = setInterval(refresh, 5000);
  } catch (e) { $("who").textContent = "not connected"; clearInterval(timer); }
}

$("login").onsubmit = (e) => { e.preventDefault(); token = $("token").value.trim(); $("token").value = ""; connect(); };
$("sound").onclick = () => { // the click is the user gesture browsers require before audio may play
  if (audio) { audio.close(); audio = null; } else { audio = new AudioContext(); beep(); }
  $("sound").textContent = audio ? "Alarm sound on" : "Turn on alarm sound";
  $("sound").setAttribute("aria-pressed", String(!!audio));
};
$("filter").onchange = () => setView(view, 0);
$("tab-active").onclick = () => setView("active", 0);
$("tab-history").onclick = () => setView("history", 0);
$("newer").onclick = () => setView("history", Math.max(0, offset - PAGE));
$("older").onclick = () => setView("history", offset + PAGE);
$("close").onclick = () => { $("drawer").hidden = true; };
$("newtok").onclick = () => { $("newtok").hidden = true; };
$("cancel-dlg").querySelector("form").onsubmit = (e) => {
  if (e.submitter && e.submitter.value === "cancel") setStatus(cancelling, "CANCELLED", { reason: e.target.elements.reason.value.trim() });
};
$("behalf-dlg").querySelector("form").onsubmit = (e) => {
  if (!e.submitter || e.submitter.value !== "go") return;
  const f = e.target.elements, at = dz(f.at.value);
  setStatus(behalf.m, behalf.next, { reason: f.reason.value.trim(), ...(at ? { event_time: at } : {}) });
};
$("newm").elements.dispatched.oninput = renderVehicles; // back-fill unlocks busy vehicles in the list
$("newm").onsubmit = async (e) => {
  e.preventDefault();
  const f = e.target.elements; // assigned_driver_id omitted: the server takes the vehicle's paired driver
  const at = dz(f.dispatched.value); // back-fill only: the whole paper-log mission in one request
  const body = { pickup_address: f.addr.value.trim(), assigned_vehicle_id: f.veh.value,
    ...(pickup ? { pickup_lat: pickup.lat, pickup_lng: pickup.lng } : {}),
    ...(at ? { dispatched_at: at, steps: backfillSteps(f) } : {}) };
  try { await api("POST", "/missions", body); e.target.reset(); setPickup(null); } catch (err) { /* toast shown */ }
  refresh();
};
$("newv").onsubmit = async (e) => {
  e.preventDefault();
  const f = e.target.elements;
  try { await api("POST", "/vehicles", { operator: f.operator.value, registration: f.registration.value }); e.target.reset(); } catch (err) { /* toast shown */ }
  refresh();
};
$("pairf").onsubmit = async (e) => {
  e.preventDefault();
  const f = e.target.elements;
  try { await api("PUT", `/vehicles/${enc(f.veh.value)}/driver`, { driver_id: f.drv.value || null }); } catch (err) { /* toast shown */ }
  refresh();
};
$("newd").onsubmit = async (e) => {
  e.preventDefault();
  const f = e.target.elements, phone = f.phone.value.trim();
  try {
    // The create response's raw token is dropped on purpose (S3): the phone pairs with a 10-minute code instead.
    const d = await api("POST", "/drivers", { name: f.name.value, ...(phone ? { phone } : {}) });
    e.target.reset();
    await pairingCode(d);
  } catch (err) { /* toast shown */ }
  refresh();
};
$("map-search-btn").onclick = async () => {
  const q = $("map-search-input").value.trim();
  if (!q) return;
  try {
    const url = "https://nominatim.openstreetmap.org/search?format=json&q=" + enc(q + ", Dhaka, Bangladesh") + "&countrycodes=bd&limit=5";
    const r = await fetch(url, { headers: { "Accept-Language": "en" } });
    const data = await r.json();
    if (!data || !data.length) { toast("No location found for: " + q); return; }
    const lat = parseFloat(data[0].lat), lng = parseFloat(data[0].lon);
    map.setView([lat, lng], 15);
    setPickup({ lat, lng });
    toast("Map moved to: " + (data[0].display_name.split(",")[0] || q));
  } catch (err) { toast("Search error: " + err.message); }
};
$("map-search-input").onkeydown = (e) => {
  if (e.key === "Enter") { e.preventDefault(); $("map-search-btn").click(); }
};

$("btn-reports").onclick = async () => {
  try {
    const data = await api("GET", "/reports/response-times");
    const tbody = $("reports-table").tBodies[0];
    const s = data.summary || {};
    const fmt = (v, unit) => (v != null ? `${v} ${unit}` : "-");
    const rows = [
      ["Dispatch to Ack", s.dispatch_to_ack_s ? s.dispatch_to_ack_s.count : 0, fmt(s.dispatch_to_ack_s ? s.dispatch_to_ack_s.median : null, "s"), fmt(s.dispatch_to_ack_s ? s.dispatch_to_ack_s.p90 : null, "s"), fmt(s.dispatch_to_ack_s ? s.dispatch_to_ack_s.min : null, "s"), fmt(s.dispatch_to_ack_s ? s.dispatch_to_ack_s.max : null, "s")],
      ["Ack to Scene", s.ack_to_scene_m ? s.ack_to_scene_m.count : 0, fmt(s.ack_to_scene_m ? s.ack_to_scene_m.median : null, "min"), fmt(s.ack_to_scene_m ? s.ack_to_scene_m.p90 : null, "min"), fmt(s.ack_to_scene_m ? s.ack_to_scene_m.min : null, "min"), fmt(s.ack_to_scene_m ? s.ack_to_scene_m.max : null, "min")],
      ["Scene to Hospital", s.scene_to_hospital_m ? s.scene_to_hospital_m.count : 0, fmt(s.scene_to_hospital_m ? s.scene_to_hospital_m.median : null, "min"), fmt(s.scene_to_hospital_m ? s.scene_to_hospital_m.p90 : null, "min"), fmt(s.scene_to_hospital_m ? s.scene_to_hospital_m.min : null, "min"), fmt(s.scene_to_hospital_m ? s.scene_to_hospital_m.max : null, "min")],
      ["Turnaround Time", s.total_turnaround_m ? s.total_turnaround_m.count : 0, fmt(s.total_turnaround_m ? s.total_turnaround_m.median : null, "min"), fmt(s.total_turnaround_m ? s.total_turnaround_m.p90 : null, "min"), fmt(s.total_turnaround_m ? s.total_turnaround_m.min : null, "min"), fmt(s.total_turnaround_m ? s.total_turnaround_m.max : null, "min")],
    ];
    tbody.replaceChildren(...rows.map((r) => h("tr", {}, ...r.map((c) => td(String(c))))));
    $("reports-dlg").showModal();
  } catch (err) { /* toast shown */ }
};
$("btn-export-csv").onclick = async () => {
  try {
    const res = await fetch("/reports/response-times?format=csv", {
      headers: { Authorization: "Bearer " + token }
    });
    if (!res.ok) throw new Error("HTTP " + res.status);
    const blob = await res.blob();
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `response_times_${new Date().toISOString().slice(0, 10)}.csv`;
    a.click();
    setTimeout(() => URL.revokeObjectURL(url), 10000);
  } catch (err) { toast("CSV export failed: " + err.message); }
};

if (token) connect();
