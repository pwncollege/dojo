#!/bin/bash
# Test script to verify Splunk is receiving logs from all containers

set -e

SPLUNK_USER="admin"
SPLUNK_PASS="$1"
SPLUNK_HOST="127.0.0.1"
SPLUNK_PORT="8089"
HEC_PORT="8088"
HEC_TOKEN="11111111-1111-1111-1111-111111111111"

echo "=== Splunk Integration Test ==="
echo ""

# Check if Splunk is running
echo "[+] Checking if Splunk container is running..."
if docker ps | grep -q splunk; then
    echo "    ✓ Splunk container is running"
else
    echo "    ✗ Splunk container is not running"
    echo "    Run: docker-compose --profile main up -d splunk"
    exit 1
fi

# Wait for Splunk to be ready
echo "[+] Waiting for Splunk to be ready..."
for i in {1..30}; do
    if curl -s -k -u ${SPLUNK_USER}:${SPLUNK_PASS} https://${SPLUNK_HOST}:${SPLUNK_PORT}/services/server/info >/dev/null 2>&1; then
        echo "    ✓ Splunk is ready"
        break
    fi
    if [ $i -eq 30 ]; then
        echo "    ✗ Splunk is not responding after 30 seconds"
        exit 1
    fi
    sleep 1
done

# Test HEC endpoint
echo "[+] Testing HTTP Event Collector (HEC)..."
response=$(curl -s -w "\n%{http_code}" -k http://${SPLUNK_HOST}:${HEC_PORT}/services/collector/event \
    -H "Authorization: Splunk ${HEC_TOKEN}" \
    -d '{"event": "test event from integration script", "sourcetype": "test"}')

http_code=$(echo "$response" | tail -n1)
body=$(echo "$response" | head -n-1)

if [ "$http_code" = "200" ]; then
    echo "    ✓ HEC is working (HTTP $http_code)"
else
    echo "    ✗ HEC test failed (HTTP $http_code)"
    echo "    Response: $body"
fi

# Check logging configuration for containers
echo "[+] Checking container logging configuration..."
containers=$(docker ps --format "table {{.Names}}" | tail -n +2)
configured=0
total=0

for container in $containers; do
    total=$((total + 1))
    log_driver=$(docker inspect $container --format '{{.HostConfig.LogConfig.Type}}' 2>/dev/null || echo "unknown")
    if [ "$log_driver" = "splunk" ]; then
        configured=$((configured + 1))
        echo "    ✓ $container is configured for Splunk logging"
    else
        echo "    ✗ $container is using $log_driver driver (not Splunk)"
    fi
done

echo ""
echo "Summary: $configured/$total containers configured for Splunk logging"

# Generate test logs
echo ""
echo "[+] Generating test logs from configured containers..."
for container in $containers; do
    log_driver=$(docker inspect $container --format '{{.HostConfig.LogConfig.Type}}' 2>/dev/null || echo "unknown")
    if [ "$log_driver" = "splunk" ]; then
        docker exec $container sh -c "echo '[TEST] Splunk integration test log from $container at $(date)'" 2>/dev/null || true
    fi
done

echo ""
echo "[+] Test complete!"
echo ""
echo "To view logs in Splunk:"
echo "  1. Access Splunk Web UI at http://${SPLUNK_HOST}:8000"
echo "  2. Login with username: ${SPLUNK_USER} password: ${SPLUNK_PASS}"
echo "  3. Search for: index=main source=\"docker\""
echo "  4. Or search for test logs: index=main \"[TEST]\""
