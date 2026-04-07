#!/usr/bin/env python3

import subprocess
import json
from datetime import datetime
import logging
import os
import sys
import concurrent.futures
import threading

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(message)s')


class HeuristicController:
    def __init__(self):
        self.upf1 = "upf1"
        self.upf2 = "upf2"
        self.tc_interface = "eth1"
        self.measure_interface = "upfgtp"

        self.sla_ue1 = 20.0
        self.sla_ue2 = 12.0

        self.rate_ue1 = 20
        self.rate_ue2 = 10

        self.min_ue1 = 10
        self.min_ue2 = 5
        self.max_ue1 = 50
        self.max_ue2 = 50

        self.step = 2
        self._stop_event = threading.Event()

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

    def measure_throughput(self, upf, duration=3):
        def read_rx_bytes(upf_name):
            result = self.run_cmd(
                f"docker exec {upf_name} cat /proc/net/dev"
            )
            for line in result.stdout.splitlines():
                if "upfgtp" in line:
                    fields = line.split()
                    return int(fields[1])  # Receive bytes column
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

    def decide(self, ue1_tput, ue2_tput):
        ue1_ok = ue1_tput >= self.sla_ue1
        ue2_ok = ue2_tput >= self.sla_ue2

        action = "hold"

        if ue1_ok and ue2_ok:
            return "hold"

        if (not ue1_ok) and ue2_ok:
            if self.rate_ue2 - self.step >= self.min_ue2:
                self.rate_ue1 += self.step
                self.rate_ue2 -= self.step
                action = "shift_2mbit_to_ue1"

        elif (not ue2_ok) and ue1_ok:
            if self.rate_ue1 - self.step >= self.min_ue1:
                self.rate_ue1 -= self.step
                self.rate_ue2 += self.step
                action = "shift_2mbit_to_ue2"

        else:
            deficit1 = max(0.0, self.sla_ue1 - ue1_tput)
            deficit2 = max(0.0, self.sla_ue2 - ue2_tput)

            if deficit1 > deficit2:
                if self.rate_ue2 - self.step >= self.min_ue2:
                    self.rate_ue1 += self.step
                    self.rate_ue2 -= self.step
                    action = "both_bad_prioritize_ue1"
            elif deficit2 > deficit1:
                if self.rate_ue1 - self.step >= self.min_ue1:
                    self.rate_ue1 -= self.step
                    self.rate_ue2 += self.step
                    action = "both_bad_prioritize_ue2"
            else:
                action = "both_bad_equal_hold"

        self.clamp_rates()
        return action

    def run(self):
        logging.info("Starting heuristic controller.")
        results = []
        executor = concurrent.futures.ThreadPoolExecutor(max_workers=2)

        try:
            self.init_tc(self.upf1, self.rate_ue1)
            self.init_tc(self.upf2, self.rate_ue2)

            while True:
                future_ue1 = executor.submit(self.measure_throughput, self.upf1, duration=5)
                future_ue2 = executor.submit(self.measure_throughput, self.upf2, duration=5)
                ue1_tput = future_ue1.result()
                ue2_tput = future_ue2.result()

                action = self.decide(ue1_tput, ue2_tput)

                ok1, err1 = self.apply_rate(self.upf1, self.rate_ue1)
                ok2, err2 = self.apply_rate(self.upf2, self.rate_ue2)

                log_entry = {
                    "timestamp": datetime.now().isoformat(),
                    "ue1_throughput_mbps": ue1_tput,
                    "ue2_throughput_mbps": ue2_tput,
                    "sla_ue1_mbps": self.sla_ue1,
                    "sla_ue2_mbps": self.sla_ue2,
                    "rate_ue1_mbit": self.rate_ue1,
                    "rate_ue2_mbit": self.rate_ue2,
                    "action": action,
                    "tc_apply_upf1_ok": ok1,
                    "tc_apply_upf2_ok": ok2,
                    "tc_apply_upf1_err": err1,
                    "tc_apply_upf2_err": err2,
                }
                results.append(log_entry)

                print(f"\n[{datetime.now().strftime('%H:%M:%S')}]")
                print(f"  UE1: {ue1_tput:5.1f} Mbps | target {self.sla_ue1:.1f} | rate {self.rate_ue1} mbit")
                print(f"  UE2: {ue2_tput:5.1f} Mbps | target {self.sla_ue2:.1f} | rate {self.rate_ue2} mbit")
                print(f"  Action: {action}")

        except KeyboardInterrupt:
            self._stop_event.set()
            executor.shutdown(wait=False)
            print("\nStopping heuristic controller...")

            results_dir = f"../../experimentation_results/heuristic/heuristic_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
            os.makedirs(results_dir, exist_ok=True)

            out_file = os.path.join(results_dir, "results.json")
            with open(out_file, "w") as f:
                json.dump(results, f, indent=2)

            logging.info(f"Results saved to {out_file}")


def main():
    print("\n=== Heuristic Controller for 5G Slicing ===\n")
    print("This script will:")
    print("  1. Measure throughput for UE1 and UE2")
    print("  2. Compare against SLA targets (UE1: 20 Mbps, UE2: 12 Mbps)")
    print("  3. Adjust tc HTB rates using a simple heuristic")
    print("  4. Save results to experimentation_results/\n")

    print("Make sure traffic generation script is running in another terminal!\n")

    response = input("Start controller? (y/n): ")
    if response.lower() != "y":
        print("Exiting.")
        sys.exit(0)

    controller = HeuristicController()
    controller.run()


if __name__ == "__main__":
    main()
