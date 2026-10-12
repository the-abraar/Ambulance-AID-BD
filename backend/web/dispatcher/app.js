"use strict";
// All dynamic text goes through h()/textContent, never innerHTML, so API data cannot inject markup.
const STALE_MS = 120000;
let token = "", vehicles = [], drivers = [], transitions = {}, timer = null;
try { token = sessionStorage.getItem("tok") || ""; } catch (e) { /* storage blocked: token lives in memory only */ }

const $ = (id) => document.getElementById(id);
function h(tag, props, ...kids) {
  const e = document.createElement(tag);
  Object.assign(e, props || {});
  for (const k of kids) e.append(k);
  return e;
}
function toast(msg) {
  const t = h("div", { className: "toast", textContent: msg });
  $("toasts").append(t);
  setTimeout(() => t.remove(), 6000);
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
    if (typeof d !== "string") d = JSON.stringify(d || "");
    if ([401, 403, 409].includes(r.status)) toast(r.status + ": " + d);
    else if (r.status >= 400) toast("Error " + r.status + " " + d);
    throw new Error(r.status + " " + d);
  }
  return r.status === 204 ? null : r.json();
}
const short = (s) => (s ? s.slice(0, 8) : "-");
const nameOf = (list, key, id, f) => { const x = list.find((i) => i[key] === id); return x ? f(x) : short(id); };

function ageText(ts) {
  const ms = Date.now() - Date.parse(ts);
  return ms < 60000 ? Math.round(ms / 1000) + " s ago" : Math.round(ms / 60000) + " min ago";
}
function fill(tbody, rows) { tbody.replaceChildren(...rows); }

function renderVehicles() {
  fill($("vehicles").tBodies[0], vehicles.map((v) => {
    const p = v.last_ping, stale = !p || Date.now() - Date.parse(p.ts) > STALE_MS;
    return h("tr", {}, h("td", { textContent: v.registration }), h("td", { textContent: v.operator }),
      h("td", { textContent: v.active ? "yes" : "no" }),
      h("td", { className: stale ? "stale" : "fresh",
        textContent: p ? `${p.lat.toFixed(5)}, ${p.lng.toFixed(5)} (${ageText(p.ts)}${stale ? ", STALE" : ""})` : "no ping (STALE)" }));
  }));
  const sel = $("newm").elements.veh, cur = sel.value;
  sel.replaceChildren(h("option", { value: "", textContent: "(none)" }),
    ...vehicles.filter((v) => v.active).map((v) => h("option", { value: v.vehicle_id, textContent: v.registration })));
  sel.value = cur;
}
function renderDrivers() {
  fill($("drivers").tBodies[0], drivers.map((d) => h("tr", {}, h("td", { textContent: d.name }), h("td", { textContent: d.driver_id }),
    h("td", {}, h("button", { textContent: "Rotate token", onclick: () => rotateToken(d) }),
      h("button", { textContent: "Revoke", onclick: () => revokeToken(d) })))));
  const sel = $("newm").elements.drv, cur = sel.value;
  sel.replaceChildren(h("option", { value: "", textContent: "(none)" }),
    ...drivers.map((d) => h("option", { value: d.driver_id, textContent: d.name })));
  sel.value = cur;
}
function renderMissions(ms) {
  fill($("missions").tBodies[0], ms.map((m) => {
    const acts = h("td");
    for (const next of transitions[m.status] || [])
      acts.append(h("button", { textContent: "-> " + next, onclick: () => setStatus(m.mission_id, next) }));
    acts.append(h("button", { textContent: "Audit", onclick: () => showAudit(m.mission_id) }));
    return h("tr", {}, h("td", {}, h("code", { textContent: short(m.mission_id), title: m.mission_id })),
      h("td", { textContent: m.status }), h("td", { textContent: m.pickup_address }),
      h("td", { textContent: m.assigned_vehicle_id ? nameOf(vehicles, "vehicle_id", m.assigned_vehicle_id, (v) => v.registration) : "-" }),
      h("td", { textContent: m.assigned_driver_id ? nameOf(drivers, "driver_id", m.assigned_driver_id, (d) => d.name) : "-" }),
      h("td", { textContent: new Date(m.updated_at).toLocaleTimeString() }), acts);
  }));
}

async function refresh() {
  if (!token) return;
  try {
    const f = $("filter").value;
    [vehicles, drivers] = await Promise.all([api("GET", "/vehicles"), api("GET", "/drivers")]);
    renderVehicles(); renderDrivers();
    renderMissions(await api("GET", "/missions" + (f ? "?status=" + encodeURIComponent(f) : "")));
  } catch (e) { /* toast already shown */ }
}
async function setStatus(id, status) {
  try { await api("PATCH", `/missions/${id}/status`, { status }); } catch (e) { /* toast shown */ }
  refresh();
}
async function rotateToken(d) {
  try {
    const r = await api("POST", `/drivers/${encodeURIComponent(d.driver_id)}/token/rotate`);
    $("newtok").textContent = `New token for ${d.name} (shown once, copy now; the old one no longer works; expires ${new Date(r.expires_at).toLocaleDateString()}): ${r.token}`;
    $("newtok").hidden = false;
  } catch (e) { /* toast shown */ }
}
async function revokeToken(d) {
  if (!confirm(`Revoke ${d.name}'s token? The driver is signed out until you rotate a new one.`)) return;
  try { await api("POST", `/drivers/${encodeURIComponent(d.driver_id)}/token/revoke`); toast(`Token revoked for ${d.name}`); } catch (e) { /* toast shown */ }
}
async function showAudit(id) {
  try {
    const rows = await api("GET", `/missions/${id}/audit`);
    $("audit").replaceChildren(...rows.map((r) => h("li", { textContent: `${r.ts}  ${r.from_status || "(new)"} -> ${r.to_status}  by ${short(r.user_id)}` })));
    $("drawer").hidden = false;
  } catch (e) { /* toast shown */ }
}

async function connect() {
  try {
    const me = await api("GET", "/me");
    if (me.role !== "dispatcher") { toast("403: this console needs a dispatcher token"); return; }
    $("who").textContent = "connected";
    transitions = await api("GET", "/meta/transitions");
    const f = $("filter");
    f.replaceChildren(h("option", { value: "", textContent: "All" }),
      ...Object.keys(transitions).map((s) => h("option", { value: s, textContent: s })));
    try { sessionStorage.setItem("tok", token); } catch (e) { /* ignore */ }
    clearInterval(timer);
    await refresh();
    timer = setInterval(refresh, 5000);
  } catch (e) { $("who").textContent = "not connected"; clearInterval(timer); }
}

$("login").onsubmit = (e) => { e.preventDefault(); token = $("token").value.trim(); $("token").value = ""; connect(); };
$("filter").onchange = refresh;
$("close").onclick = () => { $("drawer").hidden = true; };
$("newm").onsubmit = async (e) => {
  e.preventDefault();
  const f = e.target.elements, lat = Number(f.lat.value), lng = Number(f.lng.value);
  const body = { pickup_address: f.addr.value.trim() || `${lat}, ${lng}`, pickup_lat: lat, pickup_lng: lng,
    assigned_vehicle_id: f.veh.value || null, assigned_driver_id: f.drv.value || null };
  try { await api("POST", "/missions", body); e.target.reset(); } catch (err) { /* toast shown */ }
  refresh();
};
$("newv").onsubmit = async (e) => {
  e.preventDefault();
  const f = e.target.elements;
  try { await api("POST", "/vehicles", { operator: f.operator.value, registration: f.registration.value }); e.target.reset(); } catch (err) { /* toast shown */ }
  refresh();
};
$("newd").onsubmit = async (e) => {
  e.preventDefault();
  try {
    const d = await api("POST", "/drivers", { name: e.target.elements.name.value });
    $("newtok").textContent = `Driver token for ${d.name} (shown once, copy now): ${d.token}`;
    $("newtok").hidden = false; e.target.reset();
  } catch (err) { /* toast shown */ }
  refresh();
};
if (token) connect();
