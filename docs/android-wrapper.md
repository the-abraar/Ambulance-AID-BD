# Android wrapper (driver app)

Android Chrome gives a web page no GPS once it is in the background or the screen is off, and the driver app's own
"Navigate" button sends it to the background. The wrapper in `android/` loads the same driver web app in a WebView and
posts pings from a native foreground location service, which keeps running in both cases. On shift, the same service
also runs between missions: it reports the free vehicle once a minute and rings the phone when a new mission arrives.

## What it is

- `MainActivity`: a WebView on `BASE_URL` with JavaScript and DOM storage on. Links to any other origin (`tel:`, `sms:`,
  Google Maps, other sites) open in their own apps. Back goes back in the page, then to the home screen (the page and
  tracking stay alive). It explains each permission before Android asks: precise location, notifications (Android 13+),
  battery optimisation, and once per install on Xiaomi, Oppo, Vivo and Realme a short guide (Autostart, battery
  "No restrictions", lock in Recent apps) with buttons for the app's settings and dontkillmyapp.com.
- `TrackingService`: a foreground service of type `location` with the notification "Tracking vehicle <id>". It is
  started only from the visible app (`startTracking` refuses otherwise), so it needs no `ACCESS_BACKGROUND_LOCATION`.
  It holds a partial wake lock that lapses 10 minutes after the last fix or poll. If Android kills the app and later
  restarts the service in the background, the service does not run blind (Android gives a background-started location
  service no fixes on 11-13 and refuses it on 14+): it posts "Tracking stopped: open the app" and stops.
- `PingQueue` (plain Kotlin, unit-tested): the sampling and drop rules below.
- `ShiftWatch` (plain Kotlin, unit-tested): what the shift poll's answer means (alert, clear, stop, mission or not).
- App Link: `BASE_URL`'s scheme, host and path (`/driver/`) open in the app, so scanning the console's pairing QR
  (`/driver/#pair=CODE`) pairs the app, not the browser. Android verifies it against the server's
  `/.well-known/assetlinks.json`, which lists `AMBULANCE_ANDROID_CERT_SHA256` (the signing key's fingerprint:
  `keytool -list -v -keystore <release keystore>`). Until that is set, the link opens the browser, and the console tells
  drivers with the app to type the code instead.
- No runtime dependencies (platform `LocationManager`, no Play Services, no AndroidX). `minSdk` 26, `targetSdk` 36.

## JavaScript interface: `window.AmbulanceNative`

Present only inside the wrapper. Methods are synchronous.

| Call | Does |
|---|---|
| `startTracking(json)` | `json` is a string: `{"baseUrl", "token", "vehicleId", "missionId", "shift"}`. `missionId` is `""` on shift between missions; `shift` is `true` for shift mode. Starts tracking, or replaces the running session (for example after a token rotation). Returns `true` when started; `false` when the app is not on screen, the JSON is invalid, `baseUrl` is not the wrapper's own origin, token or vehicle is empty, location permission is missing (the wrapper then asks for it again), or Android refuses to start the service. Call it only while `document.visibilityState === 'visible'`. |
| `stopTracking()` | Stops tracking (mission finished off shift, shift ended, sign-out). |
| `isTracking()` | `true` from a successful `startTracking` until a stop. Check it on page load: the service may have been stopped while the page was closed. |

- Pings go to `<origin of baseUrl>/vehicles/<vehicleId>/pings` with `Authorization: Bearer <token>`. `missionId` is
  not sent (the server finds the mission from the token and vehicle); it only tells the service whether to start at the
  mission rate. On shift, pings carry `"on_shift": true`, which lets the server keep them between missions.
- A new `vehicleId` empties the queue; the same vehicle with a new token keeps it.
- While native tracking runs, the page must not use `navigator.geolocation` (it would post duplicate pings).

When the service stops by itself, the page gets a DOM event:

```js
addEventListener('ambulance-native-stopped', e => {
  // e.detail = {status, reason}
  // status 401: token revoked or expired; 403: no active mission for this driver and vehicle (mission ended or
  // reassigned); 404: unknown vehicle. reason 'rejected' for those three.
  // status 0: reason 'no-location-permission' or 'start-failed' (Android would not start the service).
  // On shift, a 401 from the mission poll also stops it (reason 'rejected').
});
```

The event is dispatched when the app is on screen: at once, or when the driver comes back to the app. A page hidden
for a long time can be frozen by the WebView, so do not rely on page JavaScript running while the app is in the
background (the native service does the pinging). A page that loads later sees `isTracking() === false`;
`isTracking()` is the source of truth.

## Shift mode: new-mission alert and free vehicles

The page shows "Start shift" (Bangla first) inside the wrapper when the driver is paired with an in-service vehicle
(`/me` `paired_vehicle_id`). The choice is kept in `localStorage` and ends with "End shift" or sign-out. While on shift:

- The service runs between missions too. Every 30 s it asks `GET /missions/current`. A new mission that is not yet
  accepted, while the app is off screen, posts a high-importance notification on the "New missions" channel: the alarm
  sound (alarm stream, so it rings in silent mode; Do Not Disturb may still block it), vibration, repeated
  (`FLAG_INSISTENT`) until the driver opens the app, accepts, or the mission ends. Once per mission; opening the app
  clears it and the page's own siren takes over. On screen, the page alerts by itself.
- Between missions it asks GPS for one fix a minute and sends it with `on_shift: true`; the server keeps one per 30 s
  for the paired vehicle only. During a mission it goes back to 5-10 s. The poll switches the rate within 30 s; the
  page also restarts the session with the new mission when it is on screen.
- Off shift, nothing changes from before: the service runs only during a mission and stops when the mission ends (403).

Why this design (the smallest that works without new accounts or dependencies):
- Polling from the existing location service, not push. FCM would wake a sleeping phone more cheaply, but it needs
  Google Play services, a Firebase project (an owner account) and a dependency. Upgrade to an FCM high-priority message
  when the host is settled; the poll then becomes the fallback.
- One foreground service, not two. A separate "polling" service would need a foreground service type Android does not
  offer for this (`dataSync` is capped at 6 hours a day on Android 15). Shift tracking is a real location use, so the
  `location` type fits, and its ongoing notification says "On shift: location every minute between missions".
- Battery: on shift the service holds a partial wake lock (the CPU never sleeps, so polls and pings keep their times)
  and GPS wakes once a minute. The cost on a cheap phone over a 12-hour shift is UNVERIFIED; plan for the phone on the
  vehicle charger. "End shift" stops it all.
- Google Play: a `location` foreground service and the battery-exemption request need a Play Console declaration (a
  video of the feature) and must be user-started and visible, which "Start shift" and the ongoing notification are. The
  pilot sideloads the APK, so this matters only for a Play listing. No full-screen intent (Android 14 limits it to
  calling and alarm apps).
- Privacy: no position is kept when signed out, off shift with no mission, unpaired, or with the vehicle out of service.
  The consent draft (`docs/driver-consent-bn-draft.md`) says exactly this.

## Ping rules

- A fix is queued when its accuracy is 100 m or better, at least 5 s after the last queued fix, and either 20 m away
  from it or 10 s newer. On shift between missions: at least 60 s after the last one. GPS and network fixes are both
  used; most network fixes fail the accuracy rule.
- Body: `lat`, `lng`, `ts` (phone clock when the fix was taken), `sent_at` (phone clock when sent; `sent_at - ts` is
  the fix's age on the monotonic clock) and `accuracy` in metres. Digits are ASCII whatever the phone's language.
- Sent oldest first, one at a time, 1.1 s apart (the server allows one ping per second per vehicle).
- 2xx: next. 422 and other 4xx (except 408 and 429): dropped, retrying cannot help. 429: retried after 2 s.
  No answer, 408 or 5xx: kept, retried with backoff 2, 4, 8 ... 60 s. 401, 403, 404: tracking stops (event above).
- Fixes older than 290 s are dropped before sending (the server refuses over 300 s). At most 100 are queued.
- The queue is in memory. If Android kills the app, the system restarts the service with the last session; fixes
  queued at that moment (at most 5 minutes of them) are lost.

## Build

Needs JDK 17 or later and the Android SDK (`ANDROID_HOME`, or `sdk.dir=` in `android/local.properties`, which is
gitignored).

```sh
cd android
./gradlew testDebugUnitTest          # JVM tests for the ping queue and request JSON
./gradlew assembleDebug              # app/build/outputs/apk/debug/app-debug.apk
```

`BASE_URL` comes from the Gradle property `ambulance.baseUrl` (`-Pambulance.baseUrl=...` or a line in
`android/local.properties`). Debug defaults to `http://10.0.2.2:8000/driver/` (the host machine from the emulator); plain
HTTP is allowed only to `10.0.2.2`, and only in debug. A release build fails unless `ambulance.baseUrl` is `https://`.

## Try it on the emulator

```sh
cd backend && AMBULANCE_DEV=1 python -m app      # serves /driver/ on 127.0.0.1:8000
# bootstrap an admin, a driver and a vehicle (python -m app.bootstrap ...), pair them, create a mission
adb install -r android/app/build/outputs/apk/debug/app-debug.apk
adb emu geo fix 90.4125 23.8103                   # move with more geo fix calls
```

The web app's own geolocation fallback needs HTTPS (browsers refuse geolocation on plain HTTP), so on the emulator only
the native path reports positions. Debug builds allow `chrome://inspect` on the WebView.

On a real phone, point a debug build at an HTTPS host: `./gradlew assembleDebug -Pambulance.baseUrl=https://<host>/driver/`.

Emulator smoke test, 2026-10-14 (Android 17 image, API 37.1; not a real phone):
- Pings every 5 s while moving and every 10 s while still: in the foreground, on the home screen with the screen off,
  and with Google Maps opened from the page's Navigate button and the screen off.
- Forced deep Doze with the battery exemption: pings kept going every 5 s. Without the exemption: no network while in
  Doze; the queued fixes were sent in order when Doze ended, and later only in Doze maintenance windows (one ping
  every 15 to 35 minutes). So the battery-exemption prompt matters for a phone left still with the screen off.
- A cancelled mission (403) and a revoked token (401) stopped the service; the page got the event on screen.
- A 4 km jump (two `geo fix` calls far apart) got 422 and was dropped; tracking went on.

## Not done (owner)

- Release signing: create a keystore, add a `signingConfigs` block reading it from outside the repo, then
  `./gradlew assembleRelease -Pambulance.baseUrl=https://<real host>/driver/`. Put the key's SHA-256 in the server's
  `AMBULANCE_ANDROID_CERT_SHA256`, and check on a phone that scanning the pairing QR opens the app (UNVERIFIED: not
  run, it needs the real host).
- The real host URL.
- A device test on two or three cheap Androids (Xiaomi/Redmi, Realme, Vivo or Oppo): screen off, Navigate to Maps,
  2G, 30+ minutes. The emulator does not reproduce OEM background killers. Add for shift mode (not yet run, even on the
  emulator): a mission arriving with the phone locked in a pocket (does the alarm ring, also in silent mode and Do Not
  Disturb), battery use over a shift, and an OEM kill (does "Tracking stopped: open the app" appear).
- Google Play: battery-optimisation exemption requests and location foreground services need a declaration in the Play
  Console; distributing the APK directly to drivers avoids that for the pilot.
- A Bangla speaker should check the dialog texts (`android/app/src/main/res/values/strings.xml`). UNVERIFIED.
