# Runbook: system down or unreachable

The dispatch console and driver app are an aid, never the only channel. If either is down, dispatch continues by phone or radio. DRAFT: not yet rehearsed with an operator (see `pilot-plan.md`).

## Decide

Treat the system as down when the console will not load or shows no fresh vehicle positions for 2 minutes, or drivers report that status changes fail. A single driver with a bad phone is not an outage; see "One driver" below.

## Dispatcher: switch to fallback

1. Say on the operator's radio/phone group: "System down, use voice." Note the time.
2. Dispatch by voice: give each driver the pickup address and the mission number from a paper log (time, vehicle, driver, address, caller phone).
3. Drivers report each step by voice: en route, at scene, transporting, at hospital, completed. The dispatcher writes the time in the log.
4. Cancelled missions are logged with the reason.

## Operator on call: restore

1. Check `https://DOMAIN/healthz`: 200 `{"ok": true}` means app and database are up; 503 means the database is down or the app is unhealthy. On the host, `docker compose ps` shows which service is down.
2. If the database is unreachable, bring the host and `db` back first (`docker compose up -d`). The app and Caddy recover on their own within about 10 s once `/healthz` answers. If data is lost or corrupted, restore the newest dump (`docs/deploy.md`, "Real restore").
3. If a token leaked or a phone was lost: an admin revokes it (`POST /users/{id}/token/revoke`), and later pairs the new device (pairing code) or rotates the token. The old token stops working immediately. Tokens also expire 90 days after last use: a driver who gets 401 with no revocation needs a new pairing code. A stolen or expired admin token: on the host, `docker compose run --rm app python -m app.bootstrap revoke USER_ID`, then `... bootstrap admin NAME`.

## After recovery

1. Enter every paper-log mission in the console's new-mission form under "Back-fill from a paper log": address, vehicle (a busy one is fine), the dispatch time, each step's time from the log (leave a step empty if the log has none), how it ended and when (Dhaka time, up to 7 days back). It is recorded already over: the driver is not alerted and the vehicle stays free for live work. The audit log records the dispatcher as actor, the driver, the reason "back-fill" and both times. Keep the paper log.
2. Drivers keep the app open: queued pings (up to 5 minutes old) are sent on their own.
3. Write down the outage start and end, cause, and how many missions ran on paper. Review it with the operator within a week.

## One driver

Phone dead, no signal, or GPS denied: the driver calls the dispatcher; the dispatcher continues that mission by voice and logs it. Status changes are never queued offline, so a driver without signal cannot advance a mission; the dispatcher records the steps the driver reports by voice as changes on the driver's behalf, with a reason.
