#!/usr/bin/env python3
# scripts/parse_results.py (corrected)

import json
import glob
import os
import sys
import matplotlib.pyplot as plt
import numpy as np
from tabulate import tabulate

def parse_iperf3_json(filepath):
    """Extract key metrics from iperf3 JSON output"""
    with open(filepath, 'r') as f:
        data = json.load(f)

    if 'error' in data:
        return None

    # Extract metrics from the final summary
    end = data.get('end', {})

    # For TCP - iperf3 puts results in sum_sent or sum_received
    if 'sum_sent' in end:
        tcp_sum = end['sum_sent']  # FIXED: was looking for 'sum'
        metrics = {
            'test_type': 'TCP',
            'bits_per_second': tcp_sum.get('bits_per_second', 0),
            'bytes': tcp_sum.get('bytes', 0),
            'retransmits': tcp_sum.get('retransmits', 0),
            'sender': True
        }
    # For UDP
    elif 'sum' in end and end.get('sum', {}).get('udp'):  # FIXED: check for udp flag
        udp_sum = end['sum']
        metrics = {
            'test_type': 'UDP',
            'bits_per_second': udp_sum.get('bits_per_second', 0),
            'jitter_ms': udp_sum.get('jitter_ms', 0),
            'lost_packets': udp_sum.get('lost_packets', 0),
            'lost_percent': udp_sum.get('lost_percent', 0),
            'bytes': udp_sum.get('bytes', 0)
        }
    else:
        metrics = {'test_type': 'Unknown'}

    # Add test parameters
    start = data.get('start', {})
    test_start = start.get('test_start', {})
    metrics['protocol'] = test_start.get('protocol', 'unknown')

    # FIXED: target_bitrate might be in different locations or use -b flag
    # For TCP with -b, it's in test_start
    metrics['target_bitrate'] = test_start.get('target_bitrate', 0)

    # If no target_bitrate in test_start, try to get from cmdline
    if metrics['target_bitrate'] == 0 and 'cmdline' in start:
        cmdline = ' '.join(start['cmdline'])
        # Look for -b flag in cmdline
        import re
        b_match = re.search(r'-b\s+(\d+)([KMG])?', cmdline)
        if b_match:
            value = int(b_match.group(1))
            unit = b_match.group(2) if b_match.group(2) else ''
            # Convert to bits per second
            if unit == 'K':
                value *= 1000
            elif unit == 'M':
                value *= 1000000
            elif unit == 'G':
                value *= 1000000000
            metrics['target_bitrate'] = value

    return metrics

def generate_report(data_dir):
    """Generate a markdown report from all test results"""
    results = []

    for json_file in sorted(glob.glob(f"{data_dir}/*.json")):
        filename = os.path.basename(json_file)
        print(f"Processing: {filename}")  # Debug output
        metrics = parse_iperf3_json(json_file)

        if metrics:
            row = {
                'test': filename.replace('.json', ''),
                'type': metrics.get('test_type', 'N/A'),
                'achieved_mbps': metrics.get('bits_per_second', 0) / 1e6,
                'target_mbps': metrics.get('target_bitrate', 0) / 1e6,
            }

            if metrics['test_type'] == 'UDP':
                row['jitter_ms'] = metrics.get('jitter_ms', 0)
                row['loss_%'] = metrics.get('lost_percent', 0)
            elif metrics['test_type'] == 'TCP':
                row['retransmits'] = metrics.get('retransmits', 0)

            results.append(row)
            print(f"  → Achieved: {row['achieved_mbps']:.2f} Mbps, Target: {row['target_mbps']:.2f} Mbps")
        else:
            print(f"  → Failed to parse {filename}")

    return results

def create_plots(results, output_dir):
    """Create visualization plots"""
    # Extract data
    tests = [r['test'] for r in results]
    achieved = [r['achieved_mbps'] for r in results]
    targets = [r.get('target_mbps', 0) for r in results]

    # Throughput comparison plot
    plt.figure(figsize=(12, 6))
    x = np.arange(len(tests))
    width = 0.35

    plt.bar(x - width/2, targets, width, label='Target (Mbps)', alpha=0.7)
    plt.bar(x + width/2, achieved, width, label='Achieved (Mbps)', alpha=0.7)

    plt.xlabel('Test')
    plt.ylabel('Throughput (Mbps)')
    plt.title('Target vs Achieved Throughput')
    plt.xticks(x, tests, rotation=45, ha='right')
    plt.legend()
    plt.tight_layout()
    plt.savefig(f"{output_dir}/throughput_comparison.png")

    # Efficiency plot (% of target achieved)
    plt.figure(figsize=(12, 4))
    efficiency = [(a/t*100) if t>0 else 0 for a,t in zip(achieved, targets)]
    colors = ['green' if e >= 90 else 'orange' if e >= 70 else 'red' for e in efficiency]

    plt.bar(tests, efficiency, color=colors)
    plt.xlabel('Test')
    plt.ylabel('Efficiency (% of target)')
    plt.title('SLA Compliance: Percentage of Target Throughput Achieved')
    plt.xticks(rotation=45, ha='right')
    plt.axhline(y=90, color='g', linestyle='--', alpha=0.5, label='90% SLA')
    plt.axhline(y=70, color='orange', linestyle='--', alpha=0.5, label='70% SLA')
    plt.legend()
    plt.tight_layout()
    plt.savefig(f"{output_dir}/sla_compliance.png")

def main():
    if len(sys.argv) < 2:
        print("Usage: ./parse_results.py <data_directory>")
        sys.exit(1)

    data_dir = sys.argv[1]
    
    # Get paths to your existing directories
    script_dir = os.path.dirname(os.path.abspath(__file__))
    baseline_dir = os.path.dirname(script_dir)
    plots_dir = os.path.join(baseline_dir, 'plots')
    reports_dir = os.path.join(baseline_dir, 'reports')

    print(f"Analyzing results from: {data_dir}")
    results = generate_report(data_dir)

    # Print table
    print("\n=== Baseline Test Results ===\n")
    headers = ['Test', 'Type', 'Target (Mbps)', 'Achieved (Mbps)', 'Efficiency %']
    table_data = []

    for r in results:
        efficiency = (r['achieved_mbps'] / r['target_mbps'] * 100) if r['target_mbps'] > 0 else 0
        table_data.append([
            r['test'],
            r['type'],
            f"{r['target_mbps']:.1f}",
            f"{r['achieved_mbps']:.1f}",
            f"{efficiency:.1f}%"
        ])

    print(tabulate(table_data, headers=headers, tablefmt='grid'))

    # Create visualizations
    create_plots(results, plots_dir)
    print(f"\nPlots saved to: {plots_dir}")

    # Save report as markdown
    report_path = os.path.join(reports_dir, 'baseline_report.md')
    with open(report_path, 'w') as f:
        f.write("# Baseline Performance Report\n\n")
        f.write(f"Test Date: {os.path.basename(data_dir)}\n\n")
        f.write("## Summary Table\n\n")
        f.write(tabulate(table_data, headers=headers, tablefmt='pipe'))
        f.write("\n\n## Analysis\n\n")
        f.write("TODO: Add your analysis here\n\n")
        f.write("## Observations\n\n")
        f.write("- \n")
        f.write("- \n")
        f.write("- \n")
    
    print(f"Report saved to: {report_path}")

if __name__ == "__main__":
    main()
