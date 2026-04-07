#!/bin/bash
# Realistic traffic generator - random patterns, both UEs

UE1_IP="10.60.0.1"
UE2_IP="10.61.0.1"
SERVER="10.200.200.2"

# Function to generate random number between min and max
rand() {
    echo $(( (RANDOM % ($2 - $1 + 1)) + $1 ))
}

# Function to run random traffic for a UE
run_ue_traffic() {
    local ue_ip=$1
    local port=$2
    local ue_num=$3
    local duration=$4

    # Generate random values for THIS UE
    local protocol=$(rand 1 10)
    local bw=$(rand 5 50)
    local pkt_size=$(rand 500 1400)

    # Add a tiny delay to ensure different RANDOM values
    sleep 0.1

    if [ $protocol -le 7 ]; then
        # TCP traffic
        echo "  UE$ue_num: TCP ${bw}Mbps for ${duration}s"
        docker exec ueransim iperf3 -c $SERVER -p $port -B $ue_ip -b ${bw}M -t $duration > /dev/null 2>&1 &
    else
        # UDP traffic
        echo "  UE$ue_num: UDP ${bw}Mbps (packet size ${pkt_size}) for ${duration}s"
        docker exec ueransim iperf3 -c $SERVER -p $port -B $ue_ip -u -b ${bw}M -l $pkt_size -t $duration > /dev/null 2>&1 &
    fi
}

echo "=== Starting Realistic Traffic Generation ==="
echo "Press Ctrl+C to stop"
echo ""

# Cleanup function
cleanup() {
    echo ""
    echo "Stopping all traffic..."
    docker exec ueransim pkill iperf3
    exit 0
}

trap cleanup SIGINT

# Main loop - runs forever until Ctrl+C
while true; do
    # Random duration for this cycle (45-180 seconds)
    cycle_duration=$(rand 45 180)

    echo "[$(date +%H:%M:%S)] New cycle - ${cycle_duration}s"

    # Start traffic for both UEs with independent random values
    run_ue_traffic "$UE1_IP" "5201" "1" "$cycle_duration"
    run_ue_traffic "$UE2_IP" "5202" "2" "$cycle_duration"

    # Wait for this cycle to complete
    sleep $cycle_duration

    # Brief pause between cycles
    sleep 2

    echo ""
done
