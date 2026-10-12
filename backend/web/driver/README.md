# Driver PWA

Plain HTML/CSS/JS, no build, no dependencies. Served by the backend at `/driver/` (same origin as the API).

Files: `index.html`, `app.js`, `styles.css`, `manifest.webmanifest`, `sw.js` (caches app shell only, never API), `mock_server.py`.

Try it: `python mock_server.py 8099`, open http://127.0.0.1:8099/driver/ and enter any token (`bad` gives 401).

Behavior: pings every 5 s while a mission is active (GPS watch); failed/offline pings queue in localStorage (cap 200, entries older than 300 s dropped on replay, replay at <=1/s). Status changes are never queued; offline shows an error. Token is kept in sessionStorage only. Bangla default, toggle for English.

Limits: geolocation needs HTTPS or localhost. Status labels (bn/en) cover the real backend states DISPATCHED, EN_ROUTE_PICKUP, AT_SCENE, TRANSPORTING_PATIENT, AT_HOSPITAL, COMPLETED, CANCELLED; unknown statuses show raw (escaped).

A Navigate link (Google Maps URL from numeric pickup_lat/pickup_lng) shows when the mission has coordinates.
