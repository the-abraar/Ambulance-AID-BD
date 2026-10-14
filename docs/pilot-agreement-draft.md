# Pilot agreement: terms to agree (draft)

**DRAFT, not legal advice, needs counsel.** This is a plain-language list of the terms the owner wants in a pilot agreement. It was written by a software agent, not a lawyer. It is not contract wording. A Bangladeshi lawyer must turn it into an agreement, or reject it, before anyone signs. Items marked TODO need the owner, the operator or counsel. Background: `docs/pilot-plan.md` (scope, data, safety) and `docs/runbook-downtime.md` (fallback).

## Parties

- Operator: **[legal name, address, signatory: OWNER TODO]**, the ambulance fleet that runs the pilot.
- Provider: **[legal name or individual, address: OWNER TODO]**, who hosts and maintains the software.

## 1. What the pilot is

- The provider hosts the open-source Ambulance-AID-BD dispatch software (Apache 2.0) for one fleet with fewer than 20 vehicles, for **[8 weeks, proposed; dates: TODO]**.
- The scope is in `docs/pilot-plan.md` section 1: dispatch and vehicle visibility. There is no signal control, no 999 integration, no patient records and no payments.
- Fee: **[none / amount: OWNER TODO]**.

## 2. Advisory only

- The software is an aid to dispatch. It never replaces the operator's existing phone and radio procedures.
- The operator keeps its manual procedure and contact list working for the whole pilot. It switches to them whenever the software is down, slow or wrong (`docs/runbook-downtime.md`).
- The software gives no medical advice and makes no triage decisions.

## 3. The operator is responsible for dispatch

- Every dispatch decision, which vehicle goes, when and where, is the operator's, made by its own staff.
- The operator remains responsible for its vehicles, drivers, staff and patients, and for any licences or registrations those need.
- The provider gives no guarantee of availability, accuracy of positions, delivery of SMS, or response times. **[COUNSEL: how to state this under Bangladeshi law]**

## 4. Liability cap

- The provider's total liability under the agreement is capped at **[amount, e.g. the fees paid; COUNSEL TODO]**.
- No liability for indirect or consequential loss, as far as the law allows.
- **[COUNSEL: what cannot be excluded under Bangladeshi law, e.g. for death or personal injury caused by negligence; whether the operator needs its own insurance]**

## 5. Incident reporting

Each side tells the other as soon as possible, and within **[hours: TODO]**, of any of these:
- a mission that was in the system but was not acted on, or was acted on late, because of the software (for example nobody saw it on the console);
- an outage, wrong position, wrong status or lost data;
- a security or data breach, or a lost or stolen phone with a driver's access;
- any incident involving a patient or a collision while the app was in use.

Further terms:
- Any incident involving a patient or a collision pauses the pilot until both sides have reviewed it (`docs/pilot-plan.md` section 4).
- The provider keeps the audit logs needed for the review.
- **[COUNSEL: breach-notification duties to the regulator or to drivers under the Personal Data Protection Ordinance 2025, and their deadlines]**

## 6. Data roles

- The operator is the **controller**: it decides why and how driver and mission data are used.
- The provider is the **processor**: it processes the data only on the operator's instructions, to run the pilot.
- The data is listed in `docs/pilot-plan.md` section 3: users, drivers (name, optional phone), vehicles, missions with free-text pickup addresses, GPS pings during missions, and audit logs.
- No patient names, conditions or caller numbers. Dispatchers must not type them into the address field.
- Retention:
  - GPS pings are deleted after 90 days; backups are kept 14 days.
  - Mission and audit records are kept for **[period: COUNSEL TODO]**.
- Hosting location: **[country and provider: OWNER TODO; COUNSEL: is hosting outside Bangladesh allowed]**.
- Sub-processors:
  - the hosting provider **[TODO]**;
  - the SMS gateway (BulkSMSBD), only if SMS fallback is switched on;
  - offsite backup storage **[TODO]**.
- Security: per-user hashed tokens, admin and dispatcher roles, HTTPS, an append-only database role for the audit tables, and nightly backups. No independent security review has been done; say so.
- At the end of the pilot the provider returns the data to the operator **[format: TODO]**, then deletes it, including backups within 14 days, unless the operator asks otherwise in writing.
- Published results use aggregated, de-identified data only. Failure is a valid result and may be published (`docs/pilot-plan.md` section 2). **[Operator to agree]**
- **[COUNSEL: the processing terms the ordinance requires; whether the free-text address makes any record sensitive data]**

## 7. Drivers and tracking

- Each driver is told in Bangla, before enrolment, what is tracked, when, who sees it and for how long. Consent is recorded. The draft text is in `docs/driver-consent-bn-draft.md`.
- Tracking data is **not used for discipline**, fines or pay decisions unless the operator and its drivers agree otherwise in writing, before such use.
- A driver may decline. How that affects their work is the operator's responsibility and is stated here: **[OWNER/operator TODO]**.

## 8. Term, ending and changes

- Either side may end the pilot at any time with **[notice: TODO]**. The operator may stop using the software at once, without notice, for safety.
- Changes to the software during the pilot are announced to the operator before deploy. Status names and cancel rules are confirmed with the operator's dispatchers first.

## 9. Other terms for counsel

- Governing law and courts: **[COUNSEL TODO]**.
- Language: a Bangla version, and which version prevails: **[COUNSEL TODO]**.
- Signatures, dates and witnesses: **[COUNSEL TODO]**.
