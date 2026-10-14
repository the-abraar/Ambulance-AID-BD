# Web apps

Plain HTML/CSS/JS: no build step, no dependencies, no CDN. Both apps work under the Caddyfile's CSP
(`script-src 'self'`, `connect-src 'self'`, no inline script or style). The backend serves `dispatcher/` at
`/console/` and `driver/` at `/driver/`, on the same origin as the API. There is no mock server: use the real one
with a dev SQLite file.

## Dev start

From `backend/`, with the venv from `backend/README.md`:

    AMBULANCE_DEV=1 .venv/bin/python -m app.bootstrap admin me && AMBULANCE_DEV=1 .venv/bin/python -m app

The first command prints an admin token. Paste it into http://127.0.0.1:8000/console/, then add a vehicle and a
driver and pair them. The console shows the driver's 6-digit code and a QR of `/driver/#pair=CODE`. Open
http://127.0.0.1:8000/driver/ and type the code, or open the QR link. Data lives in `backend/dev.db`
(gitignored); delete it to start over. Browser test: `backend/tests/e2e_browser.py` (setup in its docstring).

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

## Driver app (`driver/`)

Files: `index.html`, `app.js`, `styles.css`, `manifest.webmanifest`, `sw.js`. The service worker caches only the app
shell, never API calls. Bump its cache name `C` whenever you change a cached file.

- **Sign-in:** the 6-digit code from the dispatcher (`POST /pair`), or the console's QR link `/driver/#pair=CODE`. The
  app removes the code from the address bar and history at once. A hidden "Use a token instead" fallback takes a pasted
  token. The token is kept in `localStorage`, so closing the installed app does not sign the driver out.
  Sign-out asks first, then clears the token and the ping queue. On a 401 (expired or revoked), the app shows the
  pairing form and keeps the queue.
- **New mission:** until the driver taps Accept (`POST /missions/{id}/ack`), the app flashes the card and the tab
  title, and plays a WebAudio siren and vibrates every 3 s. It also shows one notification with the address. Only
  then does it show the step buttons. Browsers allow sound only after a tap, and the app counts any tap. "Turn on
  mission alerts" also asks for notification permission.
- **Tracking (web):** while a mission is active and has a vehicle, the app runs a GPS watch, sends a ping every 5 s
  with `accuracy` and `sent_at`, and holds a screen wake lock. With no vehicle, it shows a message and never pings.
- **Offline queue:** failed pings wait in `localStorage` (cap 200). Each entry keeps its `vehicle_id` and `mission_id`.
  Replay sends, at most 1 per second, only the entries that match the current mission and are younger than 300 s.
  Status changes are never queued, and the offline text says that pings are kept for up to 5 minutes.
- **Bad networks:** every request aborts after 10 s and shows "Network slow, retrying" until the next answer. The app
  polls `/me` and `/missions/current` every 15 s and fetches `/meta/transitions` once.
- **Server feedback:** if a ping's `clock_skew_s` is over 60, the app tells the driver to fix the phone clock (tracking
  still works). For 10 minutes after a mission ends, the app shows "Cancelled by dispatcher" or "Mission completed".
- **Android wrapper:** when `window.AmbulanceNative` exists and a mission is active with a vehicle, the app calls
  `startTracking(JSON.stringify({baseUrl: location.origin, token, vehicleId, missionId}))`. It calls it again when the
  token or mission changes, and on page load when `isTracking()` is false (a running service is adopted as is).
  While the service runs, the web GPS watch stays off, so the server never gets two pings for one fix. If
  `startTracking` returns false (for example, it refused the `baseUrl`), the web path pings instead and the app retries
  native on the next poll. `stopTracking()` runs (if `isTracking()`) when the mission ends or is cancelled, and on
  sign-out or a 401. When the service stops itself, its `ambulance-native-stopped` event makes the app reload: a 401
  then routes to re-pairing, and a 403/404 shows the ended mission.
- **Language:** Bangla by default, with a toggle for English. Unknown statuses show the raw status name, escaped.
  Navigate opens Google Maps, built only from the numeric pickup coordinates.

Limits:
- Geolocation, wake lock and notifications need HTTPS or localhost.
- In a plain browser tab, Android stops GPS when the screen is off or the app is in the background, for example after
  Navigate opens Maps. This is UNVERIFIED on a device; the wrapper is the fix.
- An Android WebView has no Notification API, so inside the wrapper the native side must notify.
