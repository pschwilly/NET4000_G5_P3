#!/usr/bin/env python3
"""
RL Controller — Tabular Q-Learning for 5G Network Slice Management
Mirrors heuristic controller for fair comparison
"""

import subprocess
import json
import os
import sys
import random
import logging
from datetime import datetime
import concurrent.futures
import threading

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(message)s')


class RLController:
    def __init__(self):
        self.upf1      = "upf1"
        self.upf2      = "upf2"
        self.tc_interface = "eth1"
        self.measure_interface = "upfgtp"

        self.sla_ue1 = 20.0
        self.sla_ue2 = 12.0

        self.rate_ue1  = 20
        self.rate_ue2  = 10
        self.min_ue1   = 10
        self.min_ue2   = 5
        self.max_ue1   = 50
        self.max_ue2   = 50
        self.step      = 2
        self._stop_event = threading.Event()

        self.alpha     = 0.1
        self.gamma     = 0.9
        self.epsilon   = 0.6
        self.eps_min   = 0.05
        self.eps_decay = 0.90

        self.n_states  = 4
        self.n_actions = 3
        self.Q = [[0.0] * self.n_actions for _ in range(self.n_states)]
        self.ACTION_LABELS = ["hold", "shift_to_ue1", "shift_to_ue2"]

    def init_tc(self, upf, rate_mbit):
        cmds = [
            f"docker exec {upf} tc qdisc del dev {self.tc_interface} root 2>/dev/null || true",
            f"docker exec {upf} tc qdisc add dev {self.tc_interface} root handle 1: htb default 1",
            f"docker exec {upf} tc class add dev {self.tc_interface} parent 1: classid 1:1 htb rate {rate_mbit}mbit ceil {rate_mbit}mbit",
        ]
        for cmd in cmds:
            self.run_cmd(cmd)


    def run_cmd(self, cmd):
        return subprocess.run(cmd, shell=True, capture_output=True, text=True)

    def measure_throughput(self, upf, duration=5):
        def read_rx_bytes(upf_name):
            result = self.run_cmd(f"docker exec {upf_name} cat /proc/net/dev")
            for line in result.stdout.splitlines():
                if "upfgtp" in line:
                    fields = line.split()
                    return int(fields[1])
            return None

        before = read_rx_bytes(upf)
        if before is None:
            logging.warning(f"[{upf}] Could not read upfgtp rx bytes (before)")
            return 0.0

        self._stop_event.wait(timeout=duration)

        after = read_rx_bytes(upf)
        if after is None:
            logging.warning(f"[{upf}] Could not read upfgtp rx bytes (after)")
            return 0.0

        delta_bytes = after - before
        mbps = (delta_bytes * 8) / duration / 1e6
        return round(mbps, 2)

    def apply_rate(self, upf, rate_mbit):
        cmd = (
            f"docker exec {upf} tc class change dev {self.tc_interface} "
            f"parent 1: classid 1:1 htb rate {rate_mbit}mbit ceil {rate_mbit}mbit"
        )
        result = self.run_cmd(cmd)
        return result.returncode == 0, result.stderr.strip()

    def clamp_rates(self):
        self.rate_ue1 = max(self.min_ue1, min(self.rate_ue1, self.max_ue1))
        self.rate_ue2 = max(self.min_ue2, min(self.rate_ue2, self.max_ue2))

    def get_state(self, ue1_tput, ue2_tput):
        ue1_ok = ue1_tput >= self.sla_ue1
        ue2_ok = ue2_tput >= self.sla_ue2
        return (2 if ue1_ok else 0) + (1 if ue2_ok else 0)

    def choose_action(self, state):
        if random.random() < self.epsilon:
            return random.randint(0, self.n_actions - 1)
        return self.Q[state].index(max(self.Q[state]))

    def apply_action(self, action):
        if action == 1:
            if self.rate_ue2 - self.step >= self.min_ue2:
                self.rate_ue1 += self.step
                self.rate_ue2 -= self.step
        elif action == 2:
            if self.rate_ue1 - self.step >= self.min_ue1:
                self.rate_ue1 -= self.step
                self.rate_ue2 += self.step
        self.clamp_rates()

    def compute_reward(self, ue1_tput, ue2_tput, action):
        r = 0.0

        if ue1_tput >= self.sla_ue1:
            r += 1.0
        else:
            r -= (self.sla_ue1 - ue1_tput) / self.sla_ue1

        if ue2_tput >= self.sla_ue2:
            r += 1.0
        else:
            r -= (self.sla_ue2 - ue2_tput) / self.sla_ue2

        if action != 0:
            r -= 0.05

        return round(r, 3)

    def update_q(self, s, a, reward, s_next):
        best_next = max(self.Q[s_next])
        self.Q[s][a] += self.alpha * (reward + self.gamma * best_next - self.Q[s][a])

    def decay_epsilon(self):
        self.epsilon = max(self.eps_min, self.epsilon * self.eps_decay)

    def run(self):
        logging.info("Starting RL controller.")
        self.run_ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.out_dir = os.path.abspath(os.path.join(
            os.path.dirname(__file__),
            f"../../experimentation_results/RL/rl_{self.run_ts}"
        ))
        os.makedirs(self.out_dir, exist_ok=True)

        print(f"  α={self.alpha}  γ={self.gamma}  ε_start={self.epsilon}"
              f"  ε_decay={self.eps_decay}  ε_min={self.eps_min}")

        self.init_tc(self.upf1, self.rate_ue1)
        self.init_tc(self.upf2, self.rate_ue2)
        self.apply_rate(self.upf1, self.rate_ue1)
        self.apply_rate(self.upf2, self.rate_ue2)

        executor = concurrent.futures.ThreadPoolExecutor(max_workers=2)
        results = []

        try:
            episode = 0
            while True:
                episode += 1

                # First measurement (determine current state)
                future_ue1 = executor.submit(self.measure_throughput, self.upf1, duration=5)
                future_ue2 = executor.submit(self.measure_throughput, self.upf2, duration=5)
                ue1_tput = future_ue1.result()
                ue2_tput = future_ue2.result()
                s = self.get_state(ue1_tput, ue2_tput)

                # Choose and apply action
                action = self.choose_action(s)
                self.apply_action(action)
                ok1, err1 = self.apply_rate(self.upf1, self.rate_ue1)
                ok2, err2 = self.apply_rate(self.upf2, self.rate_ue2)

                # Second measurement (observe result of action)
                future_ue1 = executor.submit(self.measure_throughput, self.upf1, duration=5)
                future_ue2 = executor.submit(self.measure_throughput, self.upf2, duration=5)
                ue1_tput_next = future_ue1.result()
                ue2_tput_next = future_ue2.result()
                s_next = self.get_state(ue1_tput_next, ue2_tput_next)

                # Q-learning update
                reward = self.compute_reward(ue1_tput_next, ue2_tput_next, action)
                self.update_q(s, action, reward, s_next)
                self.decay_epsilon()

                ue1_flag = "✓" if ue1_tput >= self.sla_ue1 else "✗"
                ue2_flag = "✓" if ue2_tput >= self.sla_ue2 else "✗"
                print(f"\n[Ep {episode:>3}  ε={self.epsilon:.3f}]")
                print(f"  UE1: {ue1_tput:5.1f} Mbps {ue1_flag} | target {self.sla_ue1:.0f} | rate {self.rate_ue1} mbit")
                print(f"  UE2: {ue2_tput:5.1f} Mbps {ue2_flag} | target {self.sla_ue2:.0f} | rate {self.rate_ue2} mbit")
                print(f"  Action: {self.ACTION_LABELS[action]}  Reward: {reward:+.3f}  s:{s}→{s_next}")
                print(f"  Q[{s}]: {[round(v,3) for v in self.Q[s]]}")

                results.append({
                    "episode":             episode,
                    "timestamp":           datetime.now().isoformat(),
                    "ue1_throughput_mbps": ue1_tput,
                    "ue2_throughput_mbps": ue2_tput,
                    "sla_ue1_mbps":        self.sla_ue1,
                    "sla_ue2_mbps":        self.sla_ue2,
                    "state":               s,
                    "action":              action,
                    "action_label":        self.ACTION_LABELS[action],
                    "reward":              reward,
                    "rate_ue1_mbit":       self.rate_ue1,
                    "rate_ue2_mbit":       self.rate_ue2,
                    "epsilon":             round(self.epsilon, 4),
                    "tc_apply_upf1_ok":    ok1,
                    "tc_apply_upf2_ok":    ok2,
                    "ue1_sla_ok":          ue1_tput >= self.sla_ue1,
                    "ue2_sla_ok":          ue2_tput >= self.sla_ue2,
                })

        except KeyboardInterrupt:
           self._stop_event.set()
           executor.shutdown(wait=False)
           print("Stopping RL Controller...\n")

        finally:
            self._save(results, tag="final")
            self._print_q_table()

    def _save(self, results, tag="final"):

        out_file = os.path.join(self.out_dir, "results.json")
        with open(out_file, "w") as f:
            json.dump(results, f, indent=2)

        q_file = os.path.join(self.out_dir, "q_table.json")
        with open(q_file, "w") as f:
            json.dump(self.Q, f, indent=2)

        logging.info(f"[{tag}] Results saved → {out_file}")

    def _print_q_table(self):
        print("\n── Final Q-Table ──────────────────────────────────────")
        state_labels = ["(ue1✗,ue2✗)", "(ue1✗,ue2✓)", "(ue1✓,ue2✗)", "(ue1✓,ue2✓)"]
        print(f"{'':14}" + "  ".join(f"{a:>8}" for a in self.ACTION_LABELS))
        for i, row in enumerate(self.Q):
            print(f"{state_labels[i]:14}" + "  ".join(f"{v:>8.3f}" for v in row))
        print()


def main():
    print("\n=== RL Controller for 5G Slicing (Q-Learning) ===\n")
    print("This script will:")
    print("  1. Measure throughput for UE1 and UE2 (same method as heuristic)")
    print("  2. Use Q-learning to learn which tc rate adjustments satisfy SLAs")
    print("  3. Explore randomly at first, exploit learned policy over time")
    print("  4. Save results + Q-table to experimentation_results/ at the end or when interrupted\n")

    print("Make sure traffic generation script is running in another terminal!\n")

    response = input("Start controller? (y/n): ")
    if response.lower() != "y":
        print("Exiting.")
        sys.exit(0)

    controller = RLController()
    controller.run()


if __name__ == "__main__":
    main()
