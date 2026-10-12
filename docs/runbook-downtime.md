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

1. Check the host and database are up (`GET /me` with any valid token returns 200).
2. If the database is unreachable, restore the host first; the app needs no manual step once the database answers (it applies migrations at start).
3. If a token leaked or a phone was lost: dispatcher revokes it (`POST /drivers/{id}/token/revoke`), and rotates it later for a new device (`POST /drivers/{id}/token/rotate`). The old token stops working immediately.

## After recovery

1. Enter every paper-log mission that is still open; close missions that finished while down. Audit times will show entry time, not event time; note the real times in the paper log and keep it.
2. Drivers keep the app open: queued pings (up to 5 minutes old) are sent on their own.
3. Write down the outage start and end, cause, and how many missions ran on paper. Review it with the operator within a week.

## One driver

Phone dead, no signal, or GPS denied: the driver calls the dispatcher; the dispatcher continues that mission by voice and logs it. Status changes are never queued offline, so a driver without signal cannot advance a mission until back online.
