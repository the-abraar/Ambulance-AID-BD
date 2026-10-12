# Ambulance-AID-BD 🚑🚦
> **Ambulance Automated Infrastructure Dispatch & Traffic Preemption for Bangladesh**  
> An open architecture and engineering blueprint to connect emergency medical vehicles, programmable traffic signals, and citizen dispatch in Bangladesh.

---

## 🌟 Executive Summary

As major metropolitan areas in Bangladesh (such as Dhaka and Chattogram) transition toward automated, camera-enforced, and sensor-driven traffic signal systems, a generational opportunity emerges: **making traffic signals programmable and reactive to emergency services**.

In Dhaka, traffic congestion costs thousands of lives each year due to delayed emergency medical transit ("The Golden Hour"). Even when motorists wish to yield to an ambulance siren, vehicles are often locked in bumper-to-bumper gridlock with nowhere to maneuver.

**Ambulance-AID-BD** addresses this critical challenge by bridging:
1. **Emergency Vehicle Preemption (EVP):** Networked, dynamic signal preemption that flushes traffic signals ahead of approaching emergency vehicles.
2. **National Fleet Telematics & Verification:** Tamper-resistant GPS telemetry with patient-onboard verification to eliminate siren abuse.
3. **Unified Citizen & 999 CAD Platform:** A centralized dispatch system where citizens and national emergency operators (999) can view, locate, and dispatch verified Basic Life Support (BLS), Advanced Life Support (ALS), and ICU ambulances.

---

## 📐 System Architecture

```mermaid
flowchart TD
    subgraph Fleet["🚑 Ambulance Fleet Layer"]
        A1["Public Fleets (Fire Service, DGHS, Red Crescent)"]
        A2["Private & Hospital Fleets (BSMMU, Square, Evercare, etc.)"]
        T["IoT Telematics Device (GPS / OBD-II / Siren Sensor)"]
        D["Driver CAD Terminal / Tablet"]
        A1 --> T
        A2 --> T
        T <--> D
    end

    subgraph Cloud["☁️ Central Command & Cloud Engine"]
        API["API Gateway & Ingestion Engine (MQTT / mTLS)"]
        CAD["National CAD Engine (Computer-Aided Dispatch)"]
        VERIFY["Mission & State Verification Engine (Anti-Abuse)"]
        PREEMPT["Corridor & ETA Prediction Engine (Green Wave)"]
        GEO["Geospatial Database (PostGIS / Redis)"]

        T -->|MQTT / 4G Telematics| API
        D -->|Mission Status (En Route / Patient Loaded)| API
        API --> GEO
        API --> VERIFY
        VERIFY --> CAD
        VERIFY --> PREEMPT
    end

    subgraph Traffic["🚦 Intelligent Transportation System (ITS)"]
        TMC["Traffic Management Center (DNCC / DSCC / DMP)"]
        CTRL["Signal Controllers (NTCIP 1202 / SCATS / PLC Edge)"]
        LIGHTS["Physical Traffic Signals"]

        PREEMPT -->|Preemption Request API| TMC
        TMC -->|Override Phase Timing| CTRL
        CTRL --> LIGHTS
    end

    subgraph Citizens["👥 Public & Emergency Services"]
        P1["999 Emergency Dispatch Operators"]
        P2["Citizen Mobile App & Web Portal"]
        HOSP["Destination Hospital Trauma Center"]

        CAD <--> P1
        CAD <--> P2
        PREEMPT -.->|ETA & Live Stream| HOSP
    end
```

---

## 🔑 Core Pillars

### 1. Programmable Traffic Signal Preemption (EVP)
* **Cloud-to-TMC Integration:** Rather than deploying expensive proprietary infrared/radio receivers on thousands of individual signal poles, ambulances utilize standard 4G/LTE IoT trackers communicating securely with a centralized Traffic Management Center (TMC).
* **Anticipatory Queue Flushing ("Green Wave"):** Because Dhaka's arterial roads lack emergency shoulders, switching a signal green 15 seconds before arrival is useless. The engine anticipates vehicle trajectories 2–3 intersections ahead (2–4 minutes in advance), flushing queues before the ambulance reaches the junction.
* **Safety & Clearance Safeguards:** Signal controllers adhere to strict safety intervals—mandatory yellow changes, all-red intervals, and pedestrian clearance windows—ensuring preemption never induces cross-traffic collisions or harms pedestrians.

### 2. Verified Emergency Mission State Machine
* **Anti-Abuse Protocol:** To prevent drivers from bypassing traffic while empty or off-duty, preemption is strictly tied to a validated emergency mission state machine:
  * `IDLE / AVAILABLE` (Standard traffic rules apply; no preemption).
  * `DISPATCHED_TO_PATIENT` (Preemption active; corridor calculated to pickup location).
  * `PATIENT_ONBOARD` (High-priority preemption active; corridor cleared to destination hospital).
  * `MISSION_COMPLETED` (Returns to normal cycle).
* **Auditability:** Siren usage, driver telemetry, and hospital check-ins are cryptographically logged for municipal and police oversight.

### 3. Unified Ambulance Platform for Bangladesh
* **Single Pane of Glass:** Integrates fragmented fleets (government, private clinics, trust funds like Anjuman Mufidul Islam, and independent operators).
* **Real-Time Classification:** Filter by equipment level: Basic Life Support (BLS), Advanced Life Support (ALS), ICU, and Neonatal (NICU).
* **999 Integration:** Operates directly with Bangladesh National Emergency Services (999) for automated nearest-responder routing.
* **Hospital Readiness:** Streams estimated arrival time and patient vitals directly to destination hospital emergency departments so trauma teams are pre-scrubbed.

---

## 📂 Repository Contents

```text
├── README.md                                  # Repository overview and summary
├── docs/
│   ├── architecture/
│   │   ├── system-overview.md                 # End-to-end technical architecture & data flow
│   │   ├── traffic-preemption-evp.md          # Signal controllers, protocols (NTCIP/SCATS), algorithms
│   │   ├── dispatch-and-citizen-platform.md   # CAD engine, citizen booking, 999 workflows
│   │   └── bangladesh-context-and-challenges.md# Navigating gridlock, NMTs, syndicates, and policy
│   ├── api-spec/
│   │   └── openapi.yaml                       # OpenAPI 3.0 specification for CAD & Signal APIs
│   ├── security-and-anti-abuse.md             # Cryptographic verification, mTLS, audit trails
│   └── roadmap.md                             # 3-phase rollout blueprint for Bangladesh
└── LICENSE                                    # Open source license (Apache 2.0 / MIT)
```

---

## 🚦 Roadmap Summary

* **Phase 1 (Proof of Concept - Telematics & CAD):** Equip 200 ambulances across public fleets (Fire Service, DGHS, DMCH) with cellular telematics and integrate with a unified CAD dashboard.
* **Phase 2 (Corridor Pilot - Dhaka Arterial Route):** Pilot dynamic signal preemption along a high-density emergency corridor in Dhaka (e.g., *Airport Road ➔ Mohakhali ➔ Tejgaon* or *Mirpur Road ➔ Science Lab ➔ BSMMU/DMCH*).
* **Phase 3 (National Deployment & Private Fleet Onboarding):** Expand to Chattogram, Sylhet, and Rajshahi; tie commercial ambulance fitness licenses (BRTA) to telematics compliance; launch public 999 citizen app.

---

## 🤝 Contributing

We welcome contributions from transportation engineers, software developers, urban planners, public health professionals, and policymakers in Bangladesh and globally. 

Please see the [Architecture Documentation](docs/architecture/system-overview.md) to explore the system design in detail.

---

## 📄 License
This initiative and its technical specifications are released under the [Apache 2.0 License](LICENSE).
