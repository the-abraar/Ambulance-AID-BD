# Android wrapper (driver app)

Android Chrome gives a web page no GPS once it is in the background or the screen is off, and the driver app's own
"Navigate" button sends it to the background. The wrapper in `android/` loads the same driver web app in a WebView and
posts pings from a native foreground location service, which keeps running in both cases.

## What it is

- `MainActivity`: a WebView on `BASE_URL` with JavaScript and DOM storage on. Links to any other origin (`tel:`, `sms:`,
  Google Maps, other sites) open in their own apps. Back goes back in the page, then to the home screen (the page and
  tracking stay alive). It explains each permission before Android asks: precise location, notifications (Android 13+),
  battery optimisation, and once per install on Xiaomi, Oppo, Vivo and Realme a short guide (Autostart, battery
  "No restrictions", lock in Recent apps) with buttons for the app's settings and dontkillmyapp.com.
- `TrackingService`: a foreground service of type `location` with the notification "Tracking vehicle <id>". It is
  started only from the visible app, so it needs no `ACCESS_BACKGROUND_LOCATION`. It holds a partial wake lock that
  lapses 10 minutes after the last fix.
- `PingQueue` (plain Kotlin, unit-tested): the sampling and drop rules below.
- No runtime dependencies (platform `LocationManager`, no Play Services, no AndroidX). `minSdk` 26, `targetSdk` 36.

## JavaScript interface: `window.AmbulanceNative`

Present only inside the wrapper. Methods are synchronous.

| Call | Does |
|---|---|
| `startTracking(json)` | `json` is a string: `{"baseUrl", "token", "vehicleId", "missionId"}`. Starts tracking, or replaces the running session (for example after a token rotation). Returns `true` when started; `false` when the JSON is invalid, `baseUrl` is not the wrapper's own origin, token or vehicle is empty, location permission is missing (the wrapper then asks for it again), or Android refuses to start the service because the app is in the background. |
| `stopTracking()` | Stops tracking (mission finished, sign-out). |
| `isTracking()` | `true` from a successful `startTracking` until a stop. Check it on page load: the service may have been stopped while the page was closed. |

- Pings go to `<origin of baseUrl>/vehicles/<vehicleId>/pings` with `Authorization: Bearer <token>`. `missionId` is
  accepted but not sent: the server finds the mission from the token and vehicle.
- A new `vehicleId` empties the queue; the same vehicle with a new token keeps it.
- While native tracking runs, the page must not use `navigator.geolocation` (it would post duplicate pings).

When the service stops by itself, the page gets a DOM event:

```js
addEventListener('ambulance-native-stopped', e => {
  // e.detail = {status, reason}
  // status 401: token revoked or expired; 403: no active mission for this driver and vehicle (mission ended or
  // reassigned); 404: unknown vehicle. reason 'rejected' for those three.
  // status 0: reason 'no-location-permission' or 'start-failed' (Android would not start the service).
});
```

The event is dispatched when the app is on screen: at once, or when the driver comes back to the app. A page hidden
for a long time can be frozen by the WebView, so do not rely on page JavaScript running while the app is in the
background (the native service does the pinging). A page that loads later sees `isTracking() === false`;
`isTracking()` is the source of truth.

## Ping rules

- A fix is queued when its accuracy is 100 m or better, at least 5 s after the last queued fix, and either 20 m away
  from it or 10 s newer. GPS and network fixes are both used; most network fixes fail the accuracy rule.
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
  `./gradlew assembleRelease -Pambulance.baseUrl=https://<real host>/driver/`.
- The real host URL.
- A device test on two or three cheap Androids (Xiaomi/Redmi, Realme, Vivo or Oppo): screen off, Navigate to Maps,
  2G, 30+ minutes. The emulator does not reproduce OEM background killers.
- Google Play: battery-optimisation exemption requests and location foreground services need a declaration in the Play
  Console; distributing the APK directly to drivers avoids that for the pilot.
- A Bangla speaker should check the dialog texts (`android/app/src/main/res/values/strings.xml`). UNVERIFIED.
