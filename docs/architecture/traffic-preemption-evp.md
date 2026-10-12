# Emergency Vehicle Preemption (EVP) Technical Specification

## 1. Preemption vs. Priority (TSP vs. EVP)

In Intelligent Transportation Systems (ITS), transit adjustments fall into two categories:
1. **Transit Signal Priority (TSP):** Minor phase adjustments (extending green by 5–10s or truncating red) typically used for public buses. Does not interrupt safety cycles abruptly.
2. **Emergency Vehicle Preemption (EVP):** Complete operational override of the signal controller. Immediately terminates conflicting phases according to safety clearance standards and locks the requested approach green for the emergency vehicle.

**Ambulance-AID-BD** implements **EVP** with multi-intersection anticipatory queue flushing.

---

## 2. Preemption Architectures: Edge V2X vs. Centralized Cloud

| Feature | Hardware Edge (e.g. 3M Opticom / C-V2X) | Cloud-to-TMC (Ambulance-AID-BD) |
| :--- | :--- | :--- |
| **Poleside Equipment** | Optical detector / DSRC radio on every pole | None (uses existing controller network link) |
| **In-Vehicle Cost** | \$2,500 – \$5,000 per ambulance | \$150 – \$300 (standard cellular IoT tracker) |
| **Capital Cost for Dhaka** | Hundreds of millions of BDT for 1,000+ poles | Minimal (centralized cloud software API) |
| **Detection Range** | Line of sight (300–400m) | Unlimited (predictive over kilometers) |
| **Queue Flushing Ahead** | Poor (detects vehicle when it's already stuck) | **Excellent** (triggers green 2–4 mins early) |

**Conclusion:** For Bangladesh, **Centralized Cloud-to-TMC preemption** is not only orders of magnitude more affordable, but technically superior for handling high-density gridlock.

---

## 3. Anticipatory Queue Flushing ("Green Wave") Algorithm

In dense metropolitan areas like Dhaka, if a signal switches to green only when an ambulance is 100 meters away, the ambulance remains trapped behind 300 meters of queued vehicles that cannot physically move.

```text
[Downstream Junction C] <--- [Downstream Junction B] <--- [Junction A] <--- [Ambulance]
        (Normal Cycle)            (Flushing Phase)          (Holding Green)     (1.5 km away)
```

### The Flushing Algorithm:
1. **Trajectory Projection:** The Corridor Engine continuously computes the ambulance's route path ($R$) and estimated time of arrival ($ETA_i$) for downstream intersections $i \in \{1, 2, 3\}$.
2. **Queue Clearance Threshold ($T_{flush}$):**
   $$\tau_{flush} = t_{clear\_queue} + t_{safety\_transition}$$
   Where:
   * $t_{clear\_queue} = \frac{L_{queue}}{v_{discharge}}$ (Calculated from loop detectors, camera analytics, or typical peak-hour queue length).
   * $t_{safety\_transition} = t_{yellow} + t_{all\_red} + t_{ped\_clear}$.
3. **Trigger Window:**
   * When $ETA_i \le \tau_{flush} + 30\text{s}$, the preemption command is sent to Intersection $i$.
   * Intersecting queues begin moving forward, opening physical asphalt space before the ambulance arrives.
4. **Passage & Release:**
   * Once the ambulance clears the intersection (detected via GNSS geofence or stopline camera), an immediate `RELEASE_PREEMPTION` message is emitted.
   * The controller executes a graceful recovery to resume coordinated green wave cycles for standard traffic.

---

## 4. Signal Controller Integration Protocols

### 4.1 NTCIP 1202 Standard (Actuated Signal Controllers)
For traffic controllers complying with NTCIP standards, preemption commands map to standard SNMP objects:
* **Preempt Control Object (`preemptControlTable`):**
  * OID: `1.3.6.1.4.1.1206.4.2.1.6.2.1`
  * Values:
    * `preemptState`: `1 = other`, `2 = notActive`, `3 = inVerification`, `4 = inTransition`, `5 = inPreempt`, `6 = inHold`.
* **Preempt Request (`preemptDemand`):**
  * Writing `1` requests high-priority preemption for the specified preemption channel (assigned to the approach road).

### 4.2 Modern SCATS / Proprietary JSON/MQTT Edge Gateway
For modern microcontrollers, Linux edge gateways, or SCATS systems installed at municipal junctions:

```json
{
  "protocol": "AMB_EVP_V1",
  "junction_id": "DHK_MIRPUR_10_01",
  "timestamp": "2026-10-12T14:15:30.125Z",
  "command": "TRIGGER_PREEMPTION",
  "mission_id": "MSN-20261012-9841",
  "priority": "HIGH",
  "target_phase": 2,
  "approach_direction": "NORTH_TO_SOUTH",
  "estimated_arrival_utc": "2026-10-12T14:17:15.000Z",
  "max_hold_seconds": 90,
  "lease_token": "eyJhbGciOiJFUzI1NiIs..."
}
```

---

## 5. Safety Clearance & Transition Timing Safeguards

Signal safety must **never** be compromised. Instantaneous light changes cause deadly broadside collisions. Controllers enforce hardcoded safety timings at the firmware level:

1. **Active Phase Truncation:**
   * Current conflicting green terminates with a minimum duration (no abrupt flashes).
2. **Pedestrian Clearance Interval (FDW):**
   * If pedestrian "WALK" is active, transition immediately to "Flashing Don't Walk" for minimum clearance ($t_{fdw} \ge 7$s).
3. **Vehicle Clearance:**
   * Standard Yellow Change Interval: $3.5\text{s} \le t_{yellow} \le 5.0\text{s}$.
   * All-Red Clearance Interval: $2.0\text{s} \le t_{all\_red} \le 3.5\text{s}$.
4. **Preemption Green Hold:**
   * Desired approach displays solid Green.
5. **Safety Timeouts (Heartbeat Watchdog):**
   * The TMC or edge controller enforces a **maximum hold time** (default: 90 seconds).
   * If the cloud connection drops or the ambulance halts due to mechanical failure, the controller automatically releases preemption and returns to normal cyclic operation.
