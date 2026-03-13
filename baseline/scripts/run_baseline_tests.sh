#!/bin/bash
set -e

SERVER_IP=$(docker inspect -f '{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}' iperf3-server)
UE1_IP="10.60.0.1"
UE2_IP="10.61.0.1"
TEST_DURATION=30
RESULTS_DIR="../data/$(date +%Y%m%d_%H%M%S)"

mkdir -p "$RESULTS_DIR"

echo "=== Starting Baseline Tests ==="
echo "SERVER_IP=$SERVER_IP"
echo "Results will be saved to: $RESULTS_DIR"

echo "Test 1: UE1 - 10 Mbps constant"
docker exec ueransim iperf3 -c "$SERVER_IP" -p 5201 -B "$UE1_IP" -b 10M -t "$TEST_DURATION" --json > "$RESULTS_DIR/ue1_low_10m.json"

echo "Test 2: UE1 - 25 Mbps constant"
docker exec ueransim iperf3 -c "$SERVER_IP" -p 5201 -B "$UE1_IP" -b 25M -t "$TEST_DURATION" --json > "$RESULTS_DIR/ue1_medium_25m.json"

echo "Test 3: UE1 - 50 Mbps constant"
docker exec ueransim iperf3 -c "$SERVER_IP" -p 5201 -B "$UE1_IP" -b 50M -t "$TEST_DURATION" --json > "$RESULTS_DIR/ue1_high_50m.json"

echo "Test 4: UE1 - UDP 25 Mbps"
docker exec ueransim iperf3 -c "$SERVER_IP" -p 5201 -B "$UE1_IP" -u -b 25M -l 1400 -t "$TEST_DURATION" --json > "$RESULTS_DIR/ue1_udp_25m.json"

echo "=== Testing UE2 ==="

echo "Test 5: UE2 - 10 Mbps constant"
docker exec ueransim iperf3 -c "$SERVER_IP" -p 5202 -B "$UE2_IP" -b 10M -t "$TEST_DURATION" --json > "$RESULTS_DIR/ue2_low_10m.json"

echo "Test 6: UE2 - 25 Mbps constant"
docker exec ueransim iperf3 -c "$SERVER_IP" -p 5202 -B "$UE2_IP" -b 25M -t "$TEST_DURATION" --json > "$RESULTS_DIR/ue2_medium_25m.json"

echo "Test 7: UE2 - 50 Mbps constant"
docker exec ueransim iperf3 -c "$SERVER_IP" -p 5202 -B "$UE2_IP" -b 50M -t "$TEST_DURATION" --json > "$RESULTS_DIR/ue2_high_50m.json"

echo "Test 8: UE2 - UDP 25 Mbps"
docker exec ueransim iperf3 -c "$SERVER_IP" -p 5202 -B "$UE2_IP" -u -b 25M -l 1400 -t "$TEST_DURATION" --json > "$RESULTS_DIR/ue2_udp_25m.json"

echo "Test 9: Both UEs - 25 Mbps each"
docker exec ueransim sh -lc "
iperf3 -c $SERVER_IP -p 5201 -B $UE1_IP -b 25M -t $TEST_DURATION --json >/tmp/both_ue1_25m.json &
PID1=\$!
iperf3 -c $SERVER_IP -p 5202 -B $UE2_IP -b 25M -t $TEST_DURATION --json >/tmp/both_ue2_25m.json &
PID2=\$!
wait \$PID1 \$PID2
cat /tmp/both_ue1_25m.json
" > "$RESULTS_DIR/both_ue1_25m.json"

docker exec ueransim sh -lc 'cat /tmp/both_ue2_25m.json' > "$RESULTS_DIR/both_ue2_25m.json"

echo "Test 10: Both UEs - UE1 50M, UE2 10M"
docker exec ueransim sh -lc "
iperf3 -c $SERVER_IP -p 5201 -B $UE1_IP -b 50M -t $TEST_DURATION --json >/tmp/asym_ue1_50m.json &
PID1=\$!
iperf3 -c $SERVER_IP -p 5202 -B $UE2_IP -b 10M -t $TEST_DURATION --json >/tmp/asym_ue2_10m.json &
PID2=\$!
wait \$PID1 \$PID2
cat /tmp/asym_ue1_50m.json
" > "$RESULTS_DIR/asym_ue1_50m.json"

docker exec ueransim sh -lc 'cat /tmp/asym_ue2_10m.json' > "$RESULTS_DIR/asym_ue2_10m.json"

echo "=== Baseline Tests Complete ==="
echo "Results saved to: $RESULTS_DIR"
