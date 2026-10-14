# Web apps

Served by the backend, same origin as the API: `dispatcher/` at `/console/`, `driver/` at `/driver/` (see
`driver/README.md`). Browser test: `backend/tests/e2e_browser.py`.

## Dispatcher console (`/console/`)

Plain HTML/CSS/JS, no build. Sign in with a dispatcher or admin token (`python -m app.bootstrap admin NAME`).

- **Dispatch, in order:** address or landmark (a warning says no patient names or numbers: the address goes out by SMS
  and stays in the audit log), click the map for the pickup point (or pan with the arrow keys and press "Use map
  centre"), pick a free vehicle. Its paired driver goes with it. Busy vehicles, vehicles with no driver, and vehicles
  whose driver is revoked or expired are listed but cannot be picked. The pickup point is optional (without it the
  driver gets no Navigate button).
- **Map:** OpenStreetMap tiles. Vehicles with a known position: green = free, red = busy, grey dashed = stale (older
  than 120 s). A blue circle shows the phone's reported accuracy. Clicking a free vehicle selects it in the form.
- **Missions:** "Active" lists every live mission, newest first, unpaged. "History" lists all missions, 25 per page.
  The table shows the dispatch time, elapsed time and acknowledgement. A DISPATCHED mission with no acknowledgement
  after 2 minutes turns red and raises a banner. It also beeps on every poll, once "Turn on alarm sound" has been
  clicked (browsers allow audio only after a click).
- **Cancel:** a dialog shows the address, a reason is required, and the red button stands apart. Enter keeps the mission.
- **On behalf:** for a driver who cannot tap (dead phone, back-fill after an outage). "On behalf: <next step>" asks for a
  reason (required) and when it happened (optional, Dhaka time). The audit records you acting for the driver.
- **Times:** Dhaka time (UTC+6) everywhere, including the audit drawer, whatever the PC's time zone.
- **Vehicles:** any dispatcher pairs a driver with a vehicle ("Pair driver with vehicle"; "(nobody)" unpairs).
- **Drivers:** everyone sees the phone, the token state (valid until, revoked, expired) and a list of tokens expiring
  within 7 days. Admins only: "Add driver" (name, optional phone), then a pairing dialog with a 6-digit code (one use,
  10 minutes) and a QR code of `/driver/#pair=CODE`. "Pairing code" issues a new one. "Show token" rotates the token
  and shows the raw value: avoid it, because a pasted token lives in the chat for 90 days. "Revoke" signs the driver out.
- **Network:** polls `/vehicles`, `/drivers` and `/missions?active=true` every 5 s, plus the shown page in History.
  `/meta/transitions` (normal and `on_behalf=true`) is fetched once at sign-in.

**CSP.** It works under Caddy's `script-src 'self'`, `style-src 'self'` (via `default-src`) with no `unsafe-inline`:
no inline script or style. Leaflet positions its elements through `element.style` (the CSSOM), which CSP allows. The
e2e serves the console with the Caddyfile's CSP and fails on any violation. The OSM tile servers need a Referer, which
Caddy's `strict-origin-when-cross-origin` sends.

**Vendored** in `dispatcher/vendor/`, served from the app (no CDN), unmodified npm files:

| Library | Version | Licence | npm `dist.integrity` (checked on download) |
|---|---|---|---|
| Leaflet (`leaflet.js`, `leaflet.css`) | 1.9.4 | BSD-2-Clause, `vendor/leaflet/LICENSE` | `sha512-nxS1ynzJOmOlHp+iL3FyWqK89GtNL8U8rvlMOsQdTTssxZwCXh8N2NB3GDQOL+YR3XnWyZAxwQixURb+FA74PA==` |
| qrcode-generator (`qrcode.js`) | 1.4.4 | MIT, `vendor/qrcode/LICENSE` | `sha512-HM7yY8O2ilqhmULxGMpcHSF1EhJJ9yBj8gvDEuZ6M+KGJ0YY2hKpnXvRD+hZPLrDVck3ExIGhmPtSdcjC+guuw==` |

To upgrade, download the tarball from `registry.npmjs.org`, compare its sha512 with `dist.integrity`, and copy the same
files. `scripts/lint-innerhtml.sh` skips `vendor/`: minified Leaflet is not ours to annotate.

**Limits.**
- English only.
- The map needs internet for tiles. The public OSM tile servers suit a pilot's few consoles; heavier use needs a tile
  provider or an own server (OSM tile usage policy).
- Background tabs throttle timers (Chrome may poll once a minute after 5 minutes hidden), so the alarm can be late.
  Keep the console tab visible.
- Tables re-render on every poll, so keyboard focus inside a table is lost every 5 s.
- Back-filling an outage: the API accepts an event time only between the mission's creation and now, so a mission
  entered after the outage cannot carry earlier real times.
