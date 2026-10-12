# Bangladesh Context, Challenges, and Mitigations

> **FUTURE / CONCEPT ONLY.** Nothing in this document is built, agreed with any authority, or field-tested. Signal control requires prerequisites in [roadmap.md](../roadmap.md). Numbers and timings here are unsourced estimates unless cited; timing parameters conflict across docs and must be set by a licensed traffic engineer. Current mission states are in [dispatch-and-citizen-platform.md](dispatch-and-citizen-platform.md) section 4.

Deploying an automated emergency preemption and dispatch system in Bangladesh presents distinct socio-technical, physical, and infrastructural challenges compared to Western or East Asian cities. This document details these obstacles and the engineering strategies to overcome them.

---

## 1. Physical Road Geometry & Gridlock

### 1.1 The Absence of Emergency Hard Shoulders
In many global cities, motorists pull over into an emergency shoulder or wide median when hearing a siren. In Dhaka (e.g., Mirpur Road, Kazi Nazrul Islam Avenue, Pragati Sarani), roads lack hard shoulders and are bounded by concrete dividers or open drains.

* **The Failure Mode:** If an ambulance is stuck 300 meters behind a red light, turning the signal green when the ambulance is 50 meters away does nothing—cars are packed bumper-to-bumper and cannot physically yield.
* **Mitigation (Anticipatory Flushing & Early Preemption):**
  * The Corridor Engine preempts the signal **2 to 4 minutes ahead** of the ambulance's arrival.
  * This cycles the traffic forward, draining the downstream vehicle queue and creating an open lane of asphalt by the time the ambulance reaches the junction.
  * Digital Variable Message Signs (VMS) on overhead gantries warn motorists: `"Emergency Corridor Active: Merge Left"`.

---

## 2. Mixed Heterogeneous Traffic (Non-Motorized Vehicles & Motorcycles)

### 2.1 The Issue of Non-Lane-Based Flow
Traffic in Bangladesh is characterized by high heterogeneity: heavy buses, private cars, CNG auto-rickshaws, battery rickshaws, bicycles, and handcarts all sharing the same carriageway without strict lane discipline.

* **Mitigations:**
  1. **Strict Signal Clearance Windows:** Preemption must never snap signals abruptly. Yellow and all-red minimums (values UNDECIDED; this doc, `system-overview.md` and `traffic-preemption-evp.md` disagree and a licensed traffic engineer must set one table), and pedestrian flashing clearance times prevent accidents with slower non-motorized vehicles (NMT).
  2. **Motorcycle Traffic Police Integration:** For critical Tier-3 (ICU/Organ/Major Trauma) runs, the CAD engine pushes an automated escort alert to the nearest Traffic Police motorcycle patrol unit via their digital terminal to clear choke points.

---

## 3. Power Reliability & Infrastructure Resilience

### 3.1 Junction Power Outages
It is UNVERIFIED whether main Dhaka intersections have dedicated power or backups. Localized power fluctuations or grid outages can reset traffic signal controllers.

* **Mitigations:**
  * **Edge Controller Battery Backup (UPS):** All automated signal poles must feature lithium iron phosphate ($LiFePO_4$) UPS units capable of providing at least 4 hours of autonomous operation during grid interruptions.
  * **Cellular Fallback & Dual-SIM:** Signal edge gateways must include dual-SIM modems (e.g., Grameenphone + Robi) with automatic failover to prevent loss of cloud preemption commands.
  * **Autonomous Controller Watchdog:** If the controller loses cloud connectivity for more than 15 seconds, it immediately falls back to localized camera-actuated or fixed-time cyclic operation. It never remains locked in a preemption state indefinitely.

---

## 4. Socio-Economic Realities & Fleet Syndicates

### 4.1 Fragmented Ownership & Exploitative Syndicates
Most ambulances in Dhaka are reportedly privately owned (UNSOURCED; an earlier draft said over 80%) by small businesses or independent drivers. Informal syndicates often operate outside major hospitals (e.g., Dhaka Medical College Hospital, BSMMU, Suhrawardy), controlling parking and inflating prices.

* **Mitigations & Policy Levers:**
  * **Regulatory Tying (BRTA & DGHS):** Bangladesh Road Transport Authority (BRTA) and Directorate General of Health Services (DGHS) could, if they chose to, mandate that the annual vehicle fitness renewal and route permit for any ambulance require installation of a certified, tamper-proof IoT telematics unit.
  * **The "Carrot" (Priority Access):** Earlier drafts proposed granting private operators preemption rights as a commercial incentive. **Removed as a design:** it rewards fake bookings (see `judge.md` blocker 5). Preemption, if ever built, would be tied to dispatcher-verified missions only.
  * **Whistleblower & Audit Logs:** Any vehicle detected operating commercial preemption with no verified patient booking would be flagged for review. Automated citations by DMP are NOT assumed: no such authority or agreement exists.

---

## 5. Public Pedestrian Safety & Jaywalking

Dhaka is one of the densest pedestrian environments in the world. Pedestrians frequently cross arterial roads where footbridges are absent or inconvenient.

* **Mitigations:**
  * **Acoustic & Visual Junction Warnings:** When an automated signal enters an emergency preemption hold, high-decibel directional strobe indicators and Bengali voice alerts on the signal pole announce:  
    * *«জরুরী অ্যাম্বুলেন্স আসছে, রাস্তা পারাপার বন্ধ রাখুন»* ("Emergency ambulance approaching, please do not cross the road").
  * Preemption logic will not truncate pedestrian walk phases below the minimum calculated walking speed ($0.8\text{ m/s}$ based on crossing width).
