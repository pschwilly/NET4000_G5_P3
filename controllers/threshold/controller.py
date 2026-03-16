#!/usr/bin/env python3

import time
import subprocess
import json
from datetime import datetime
import logging
import os
import sys

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(message)s')

class ThresholdController:
    def __init__(self):
        self.ue1_ip = "10.60.0.1"
        self.ue2_ip = "10.61.0.1"

        # SLA thresholds (Mbps)
        self.sla_targets = {
            'ue1': {'min_throughput': 20},
            'ue2': {'min_throughput': 10}
        }

    def measure_throughput(self, ue_ip, duration=3):
        """
        Passively measure traffic using tcpdump on the UPF
        Returns throughput in Mbps
        """
        # Determine which UPF this UE uses
        if ue_ip == "10.60.0.1":
            upf = "upf1"
        else:
            upf = "upf2"

        interface = "eth1"

        # Clean up any old pcap files
        subprocess.run(f"docker exec {upf} rm -f /tmp/measure.pcap", shell=True, stderr=subprocess.DEVNULL)

        # Start tcpdump in background (capture up to 10000 packets)
        start_cmd = f"docker exec {upf} tcpdump -i {interface} -c 10000 -n -w /tmp/measure.pcap 2>/dev/null &"
        subprocess.run(start_cmd, shell=True)

        # Wait for measurement duration
        time.sleep(duration)

        # Stop tcpdump
        subprocess.run(f"docker exec {upf} pkill -f 'tcpdump.*{ue_ip}'", shell=True, stderr=subprocess.DEVNULL)

        # Give tcpdump a moment to write the file
        time.sleep(1)

        # Get packet count from the capture
        count_result = subprocess.run(
            f"docker exec {upf} tcpdump -r /tmp/measure.pcap -n 2>/dev/null | wc -l",
            shell=True, capture_output=True, text=True
        )

        # Check if traffic is UDP or TCP
        udp_count = subprocess.run(
            f"docker exec {upf} tcpdump -r /tmp/measure.pcap -n udp 2>/dev/null | wc -l",
            shell=True, capture_output=True, text=True
        )

        # Get total bytes from the capture
        bytes_result = subprocess.run(
            f"docker exec {upf} tcpdump -r /tmp/measure.pcap -n -v 2>/dev/null | grep -o 'length [0-9]*' | awk '{{sum+=$2}} END {{print sum}}'",
            shell=True, capture_output=True, text=True
        )

        # Clean up
        subprocess.run(f"docker exec {upf} rm -f /tmp/measure.pcap", shell=True, stderr=subprocess.DEVNULL)

        try:
            packet_count = int(count_result.stdout.strip())
            if packet_count == 0:
                return 0

            # Determine if traffic is mostly UDP (>50% UDP packets)
            udp_packets = int(udp_count.stdout.strip())
            is_udp = (udp_packets > packet_count / 2)

            if bytes_result.stdout.strip() and bytes_result.stdout.strip() != "0":
                total_bytes = int(bytes_result.stdout.strip())
            else:
                total_bytes = packet_count * 1000

            # Calculate throughput in Mbps
            bits_per_sec = (total_bytes * 8) / duration
            mbps = bits_per_sec / 1e6

            # Adjust for bidirectional traffic
            if is_udp:
                # UDP is mostly one-way, so no division
                pass
            else:
                # TCP is roughly symmetrical, divide by 2
                mbps = mbps / 2

            logging.debug(f"UE {ue_ip}: {mbps:.2f} Mbps ({'UDP' if is_udp else 'TCP'})")
            return mbps

        except (ValueError, subprocess.CalledProcessError) as e:
            logging.debug(f"Measurement failed: {e}")
            return 0

    def check_sla_violations(self, ue1_throughput, ue2_throughput):
        """Check if any SLA is violated"""
        violations = []

        if ue1_throughput < self.sla_targets['ue1']['min_throughput']:
            violations.append(f"UE1 throughput: {ue1_throughput:.1f} < {self.sla_targets['ue1']['min_throughput']}")

        if ue2_throughput < self.sla_targets['ue2']['min_throughput']:
            violations.append(f"UE2 throughput: {ue2_throughput:.1f} < {self.sla_targets['ue2']['min_throughput']}")

        return violations

    def run(self, interval=5):
        """Run the controller continuously until Ctrl+C"""
        logging.info(f"Starting threshold controller (interval={interval}s). Press Ctrl+C to stop.")

        results = []

        try:
            while True:
                # Measure current throughput (passively monitors YOUR traffic)
                logging.info("Measuring UE1 traffic...")
                ue1_tput = self.measure_throughput(self.ue1_ip, duration=3)

                logging.info("Measuring UE2 traffic...")
                ue2_tput = self.measure_throughput(self.ue2_ip, duration=3)

                # Check SLA violations
                violations = self.check_sla_violations(ue1_tput, ue2_tput)

                # Log results
                log_entry = {
                    'timestamp': datetime.now().isoformat(),
                    'ue1_throughput': ue1_tput,
                    'ue2_throughput': ue2_tput,
                    'violations': violations,
                }
                results.append(log_entry)

                # Console output
                print(f"\n[{datetime.now().strftime('%H:%M:%S')}]")
                print(f"  UE1: {ue1_tput:5.1f} Mbps (limit={self.ue1_limit:5.1f}) {'*** VIOLATION ***' if ue1_tput < 20 else ''}")
                print(f"  UE2: {ue2_tput:5.1f} Mbps (limit={self.ue2_limit:5.1f}) {'*** VIOLATION ***' if ue2_tput < 10 else ''}")
                if violations:
                    print(f"  VIOLATIONS: {violations}")

                # Wait for next interval (subtract measurement time)
                time.sleep(max(1, interval - 6))  # 6 seconds for two 3-second measurements

        except KeyboardInterrupt:
            print("\n\nStopping controller...")

            # Save results
            results_dir = f"../../experiment_results/threshold_test_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
            os.makedirs(results_dir, exist_ok=True)
            filename = f"{results_dir}/results.json"
            with open(filename, 'w') as f:
                json.dump(results, f, indent=2)

            logging.info(f"Results saved to {filename}")

def main():
    print("\n=== Threshold Controller for 5G Slicing ===\n")
    print("This script will:")
    print("  1. PASSIVELY MONITOR UE1 and UE2 traffic every ~8 seconds")
    print("  2. Check against SLA targets (UE1: 20 Mbps, UE2: 10 Mbps)")
    print("  3. Run until you press Ctrl+C")
    print("  4. Saves results to ~/free5gc-compose/experiment_results/\n")

    print("Make sure traffic generation script is running in another terminal!")

    response = input("\nStart controller? (y/n): ")
    if response.lower() != 'y':
        print("Exiting.")
        sys.exit(0)

    controller = ThresholdController()
    controller.run(interval=5)

if __name__ == "__main__":
    main()
