# Reinforcement Learning–Based Network Slicing in Emulated 5G Cores

Jayden Côté, Patrick Schwilden, Karar Alfaris, Nicolas Gagnon
School of Information Technology, Carleton University

---

## Overview

This project implements and compares two dynamic network slice management controllers in a containerized 5G core environment. A heuristic rule-based controller and a tabular Q-learning RL agent are evaluated under controlled and randomized traffic conditions, using SLA satisfaction and control stability as metrics.

---

## Environment

| Component | Tool |
|---|---|
| 5G Core | free5GC (Docker Compose) |
| UE / RAN Emulation | UERANSIM |
| Traffic Generation | iPerf3 |
| Bandwidth Enforcement | Linux tc HTB on upfgtp |
| Host OS | Ubuntu 22.04 |

**Two UEs, two slices, two UPF instances.**
- UE1 → upf1 → 10.60.0.1 → iPerf3 port 5201 — SLA: 20 Mbps
- UE2 → upf2 → 10.61.0.1 → iPerf3 port 5202 — SLA: 12 Mbps

---

## Controllers

### Heuristic (`controllers/heuristic/controller.py`)
Rule-based controller. Runs every 8 seconds. Measures throughput via tcpdump, compares against SLA targets, and shifts 2 Mbps toward whichever UE is underperforming. No memory of past decisions.

### RL (`controllers/RL/controller.py`)
Tabular Q-learning agent. 4 states (based on whether each UE meets its SLA), 5 actions (noop, ue1±2 Mbit, ue2±2 Mbit). Reward: +1 per UE meeting SLA, -1 per violation, -0.1 for non-noop. ε-greedy exploration decaying from 1.0 to 0.05.

---

## Traffic Scenarios

- **Controlled:** Predefined traffic phases (balanced, asymmetric, overload, low-load). 3 runs × 10 minutes per controller.
- **Randomized:** Random bandwidth (5–50 Mbps), protocol (TCP/UDP), and cycle duration (15–45 s) per UE. Single 30-minute run per controller.

---

## Results

| Metric | Heuristic | RL |
|---|---|---|
| SLA satisfaction — controlled | ~42% | ~38% |
| SLA satisfaction — randomized | ~57% | ~50% |
| Rate adjustments — controlled | ~12.7 | ~6 |
| Rate adjustments — randomized | ~53 | ~57 |

The heuristic outperformed RL on SLA satisfaction in both scenarios. The RL agent was more stable under controlled traffic but became less stable and less effective under randomized traffic, likely due to the limited state representation and short training duration.

---

## Known Issues / Setup Notes

- **gtp5g:** Use v0.9.16 — other versions caused kernel crashes
- **CHF:** Disabled in docker-compose.yaml due to CPU overload
- **iPerf3 server:** Must listen on both ports 5201 and 5202 simultaneously
- **MongoDB:** Assigned static IP to prevent Docker address conflict with UPF containers

---

## File Structure

```
free5gc-compose/
├── controllers/
│   ├── heuristic/controller.py
│   └── RL/controller.py
├── traffic_generation/
│   ├── steady_traffic.sh
│   └── random_traffic.sh
└── experimentation_results/
    ├── metrics.py
    └── [result folders]/
```
