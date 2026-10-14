# Future integrations (not built, not in the API)

> **FUTURE / CONCEPT ONLY.** Nothing here is implemented, agreed with any authority, or tested. These interfaces used
> to sit in `docs/api-spec/openapi.yaml` next to the real endpoints, which made the spec describe a different product.
> They were moved here on 2026-10-14. Signal preemption stays out of code until the gates in [roadmap.md](../roadmap.md)
> are met. The design detail lives in [traffic-preemption-evp.md](traffic-preemption-evp.md) and
> [system-overview.md](system-overview.md).

The spec now describes only what `backend/` serves. Each item below would need its own gate, owner and review before
it gets an endpoint.

## 1. Telemetry ingest from vehicle trackers

The old spec had `POST /telemetry/ingest`, authenticated by mutual TLS, for IoT trackers or driver terminals sending a
ping every 1 to 5 seconds. Each ping carried vehicle id, timestamp, latitude, longitude, heading, speed in km/h, a
siren flag and the active mission id. The server would answer 202 and queue the ping for a "corridor engine".

Today, the driver's phone posts `POST /vehicles/{id}/pings` with a bearer token. A tracker feed may replace or
supplement that if real phones prove unreliable in the background (critique action 4). Open questions: which tracker
vendors are BRTA-approved; whether the fleet already has trackers whose feed can be read; how a tracker identity maps
to a vehicle; and whether a tracker can be trusted more than a phone for any "proof of response" use.

## 2. Traffic signal preemption (TMC link)

The old spec had two internal endpoints on a private network or VPN link to the Traffic Management Center:

- **Trigger:** the corridor engine asks a junction controller to hold green for one approach. The request named the
  junction, the mission, the approach (for example north to south), the estimated arrival in seconds, a maximum hold
  time, and a short-lived lease token signed by the corridor engine (Ed25519) that the controller verifies before
  acting. The answer gave a preemption id, a state (queued, in transition, holding green, rejected) and the clearance
  time. Anti-abuse checks could reject the request (403).
- **Release:** sent as soon as the ambulance clears the junction or the hold times out, naming the junction and the
  preemption id, so the controller returns to its normal cycle.

None of this can be built without government sign-off, a signed agreement with the signal operator, a licensed traffic
engineer setting the timings, and an independent penetration test. See the gates in [roadmap.md](../roadmap.md).

## 3. Public "nearby available ambulances" query

The old spec had a public, unauthenticated `GET /ambulances/available` taking latitude, longitude, a radius in
kilometres (default 5) and a care tier (BLS, ALS, ICU, NICU). It returned vehicle id, tier, operator name, distance,
estimated pickup minutes, base fare and per-km fare in BDT.

That is a citizen marketplace, not a dispatch tool. It would publish live fleet positions and prices, so it needs a
consent and data-protection review (Personal Data Protection Ordinance 2025), verified fare rules, anti-fraud design and
an operator who agrees to be listed. The roadmap gates it behind a proven dispatch pilot.

## 4. Hosting under a government domain

The old spec listed `api.ambulance-aid.gov.bd` ("Production National Gateway"), a staging host and an internal TMC
link host. No such domains, agreements or hosting exist. The deployment today is one self-hosted instance per fleet
(see `docs/deploy.md`).
