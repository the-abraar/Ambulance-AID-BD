# Web apps

Plain HTML/CSS/JS: no build step, no dependencies, no CDN (the planned CSP is `script-src 'self'; connect-src 'self'`).
The backend serves `dispatcher/` at `/console/` and `driver/` at `/driver/`, on the same origin as the API. There is no
mock server: use the real one with a dev SQLite file.

## Dev start

From `backend/`, with the venv from `backend/README.md`:

    AMBULANCE_DEV=1 .venv/bin/python -m app.bootstrap admin me && AMBULANCE_DEV=1 .venv/bin/python -m app

The first command prints an admin token. Paste it into http://127.0.0.1:8000/console/, then add a vehicle and a
driver, pair them, and issue the driver a pairing code (or `POST /drivers/{id}/pairing-code`). Open
http://127.0.0.1:8000/driver/ and type the code, or open `/driver/#pair=CODE`. Data lives in `backend/dev.db`
(gitignored); delete it to start over. Browser test: `backend/tests/e2e_browser.py` (setup in its docstring).

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
- **Android wrapper:** when `window.AmbulanceNative` exists, the app calls
  `startTracking(JSON.stringify({baseUrl, token, vehicleId, missionId}))` when a mission becomes active, and again
  when the token rotates. It calls `stopTracking()` (if `isTracking()`) when the mission ends or is cancelled, and on
  sign-out or a 401. The web GPS watch then never runs, so the server never gets two pings for one fix.
- **Language:** Bangla by default, with a toggle for English. Unknown statuses show the raw status name, escaped.
  Navigate opens Google Maps, built only from the numeric pickup coordinates.

Limits:
- Geolocation, wake lock and notifications need HTTPS or localhost.
- In a plain browser tab, Android stops GPS when the screen is off or the app is in the background, for example after
  Navigate opens Maps. This is UNVERIFIED on a device; the wrapper is the fix.
- An Android WebView has no Notification API, so inside the wrapper the native side must notify.
