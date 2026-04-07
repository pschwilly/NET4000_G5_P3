#!/bin/bash

UE1_IP="10.60.0.1"
UE2_IP="10.61.0.1"
SERVER="10.200.200.2"

echo "=== Controlled Traffic Schedule ==="
echo "Press Ctrl+C to stop"
echo ""

cleanup() {
    echo ""
    echo "Stopping all traffic..."
    docker exec ueransim pkill -9 iperf3
    exit 0
}

trap cleanup SIGINT

run_phase() {
    local duration=$1
    local ue1_proto=$2
    local ue1_bw=$3
    local ue2_proto=$4
    local ue2_bw=$5

    echo "[$(date +%H:%M:%S)] Phase (${duration}s)"
    echo "  UE1: $ue1_proto ${ue1_bw}Mbps"
    echo "  UE2: $ue2_proto ${ue2_bw}Mbps"

    # Kill any existing traffic
    docker exec ueransim pkill -9 iperf3 > /dev/null 2>&1
    sleep 1

    # UE1
    if [ "$ue1_proto" = "UDP" ]; then
        docker exec ueransim iperf3 -c $SERVER -p 5201 -B $UE1_IP -u -b ${ue1_bw}M -t $duration > /dev/null 2>&1 &
    else
        docker exec ueransim iperf3 -c $SERVER -p 5201 -B $UE1_IP -b ${ue1_bw}M -t $duration > /dev/null 2>&1 &
    fi

    # UE2
    if [ "$ue2_proto" = "UDP" ]; then
        docker exec ueransim iperf3 -c $SERVER -p 5202 -B $UE2_IP -u -b ${ue2_bw}M -t $duration > /dev/null 2>&1 &
    else
        docker exec ueransim iperf3 -c $SERVER -p 5202 -B $UE2_IP -b ${ue2_bw}M -t $duration > /dev/null 2>&1 &
    fi

    sleep $duration
    echo ""
}

    for cycle in 1 2 3; do
        echo "[$(date +%H:%M:%S)] Starting new cycle"

        # Phase 1 - balanced (baseline)
        run_phase 120 TCP 25 TCP 15

        # Phase 2 - UE1 heavy load
        run_phase 120 UDP 45 TCP 10

        # Phase 3 - UE2 heavy load
        run_phase 120 TCP 15 UDP 30

        # Phase 4 - both overloaded
        run_phase 120 UDP 40 UDP 35

        # Phase 5 - light traffic
        run_phase 120 TCP 10 TCP 8
    done

echo "Controlled traffic schedule complete."
