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

class ThresholdController:
    def __init__(self):
        self.upf1 = "upf1"
        self.upf2 = "upf2"

        self.sla_ue1 = 20.0
        self.sla_ue2 = 12.0

        self._stop_event = threading.Event()

    def measure_throughput(self, upf, duration=5):
        def read_rx_bytes(upf_name):
            result = subprocess.run(
                f"docker exec {upf_name} cat /proc/net/dev",
                shell=True, capture_output=True, text=True
            )
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

    def check_sla_violations(self, ue1_throughput, ue2_throughput):
        """Check if any SLA is violated"""
        violations = []

        if ue1_throughput < self.sla_ue1:
            violations.append(f"UE1 throughput: {ue1_throughput:.1f} < {self.sla_ue1}")

        if ue2_throughput < self.sla_ue2:
            violations.append(f"UE2 throughput: {ue2_throughput:.1f} < {self.sla_ue2}")

        return violations

    def run(self, interval=5):
        """Run the controller continuously until Ctrl+C"""
        logging.info(f"Starting monitoring controller. Press Ctrl+C to stop.")
        results = []
        executor = concurrent.futures.ThreadPoolExecutor(max_workers=2)

        try:
            while True:
                future_ue1 = executor.submit(self.measure_throughput, self.upf1, duration=5)
                future_ue2 = executor.submit(self.measure_throughput, self.upf2, duration=5)
                ue1_tput = future_ue1.result()
                ue2_tput = future_ue2.result()

                violations = self.check_sla_violations(ue1_tput, ue2_tput)

                log_entry = {
                    "timestamp": datetime.now().isoformat(),
                    "ue1_throughput_mbps": ue1_tput,
                    "ue2_throughput_mbps": ue2_tput,
                    "sla_ue1_mbps": self.sla_ue1,
                    "sla_ue2_mbps": self.sla_ue2,
                    "ue1_sla_ok": ue1_tput >= self.sla_ue1,
                    "ue2_sla_ok": ue2_tput >= self.sla_ue2,
                    "violations": violations,
                }
                results.append(log_entry)

                print(f"\n[{datetime.now().strftime('%H:%M:%S')}]")
                print(f"  UE1: {ue1_tput:5.1f} Mbps | target {self.sla_ue1:.1f} {'*** VIOLATION ***' if ue1_tput < self.sla_ue1 else ''}")
                print(f"  UE2: {ue2_tput:5.1f} Mbps | target {self.sla_ue2:.1f} {'*** VIOLATION ***' if ue2_tput < self.sla_ue2 else ''}")
                if violations:
                    print(f"  VIOLATIONS: {violations}")

        except KeyboardInterrupt:
            self._stop_event.set()
            executor.shutdown(wait=False)
            print("\n\nStopping controller...")
            results_dir = f"../../experimentation_results/monitoring/threshold_test_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
            os.makedirs(results_dir, exist_ok=True)
            filename = f"{results_dir}/results.json"
            with open(filename, 'w') as f:
                json.dump(results, f, indent=2)
            logging.info(f"Results saved to {filename}")

def main():
    print("\n=== Threshold Controller for 5G Slicing ===\n")
    print("This script will:")
    print("  1. PASSIVELY MONITOR UE1 and UE2 traffic")
    print("  2. Check against SLA targets (UE1: 20 Mbps, UE2: 10 Mbps)")
    print("  3. Run until you press Ctrl+C")
    print("  4. Saves results to ~/free5gc-compose/experiment_results/\n")

    print("Make sure traffic generation script is running in another terminal!")

    response = input("\nStart controller? (y/n): ")
    if response.lower() != 'y':
        print("Exiting.")
        sys.exit(0)

    controller = ThresholdController()
    controller.run()

if __name__ == "__main__":
    main()
