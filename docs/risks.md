# Top 10 Risks

Ranked by severity times likelihood (judgement, not measured). Owner is a placeholder until a team exists. Source for most: `judge.md`.

| # | Risk | Mitigation | Owner |
| :-- | :--- | :--- | :--- |
| 1 | No partner or user: no operator has agreed to a pilot; product built for nobody | 20+ discovery interviews; signed pilot LOI before building UI; one operator only | TBD |
| 2 | Core signal premise false: Dhaka signals may be manual or not API-controllable (UNVERIFIED; docs previously contradicted themselves) | Keep signals out of scope; site survey and written authority agreement before any signal work; fallback to police-assisted alerts | TBD |
| 3 | Life-safety harm if signal control is ever built (crash, gridlock spillback); timing values disagree across docs | Advisory-only tool now; traffic-engineer-owned timing table, simulation, safety case, bench test before any trial | TBD |
| 4 | Data-protection and legal exposure: location and potentially health data under the Personal Data Protection Ordinance 2025; how it applies is UNVERIFIED | Legal opinion first (questions in pilot-plan.md section 3); collect minimal data; no patient data in pilot; 90-day ping retention; consent and agreement drafts for counsel; test data until cleared | TBD |
| 5 | Tool outage during a real emergency | Phone/radio fallback always active; no tool-only dispatch; downtime logging; backup/restore drill | TBD |
| 6 | Driver and operator rejection (tracking distrust, syndicates, extra workload) | Written consent in Bangla; field validation with drivers; minimal-tap UI; clear no-discipline rule agreed in advance | TBD |
| 7 | State machine mismatches real dispatch practice (initial state, cancel rules are developer guesses) | Confirm with real dispatchers before pilot; keep transitions tested and versioned | TBD |
| 8 | Security weaknesses in the backend (in-process rate limiter, single-request lock, tokens without expiry/rotation, driver bound to mission only by assignment) | Token expiry and rotation; shared rate limiter; pentest before real data; staged hardening | TBD |
| 9 | No funding or business model; pricing UNKNOWN | Test willingness to pay in pilot; unit-economics sheet; do not assume government or grant funding | TBD |
| 10 | Unsourced claims damage credibility with funders and authorities | Every number cited or labelled estimate/UNVERIFIED (done in docs); pilot baseline as first published dataset | TBD |

Also watched, not top 10: unproven deployment (compose stack run only on a laptop, no host, no offsite backups or alerting; PostGIS unused), hardware supply and type approval (not in pilot scope), public-repo exposure of future signal-control design.
