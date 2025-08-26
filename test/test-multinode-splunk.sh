#!/bin/bash
# Test script for multinode Splunk logging configuration

set -e

echo "=== Multinode Splunk Logging Test ==="
echo

# Check if running inside a dojo container
if [ ! -f /data/config.env ]; then
    echo "ERROR: This script must be run inside a dojo container"
    exit 1
fi

# Source configuration
. /data/config.env

echo "[+] Checking configuration..."
echo "   ENABLE_SPLUNK: ${ENABLE_SPLUNK}"
echo "   WORKSPACE_NODE: ${WORKSPACE_NODE}"
echo

# Early exit if Splunk is not enabled
if [ "${ENABLE_SPLUNK}" != "true" ]; then
    echo "Splunk is not enabled (should be ENABLE_SPLUNK=true)"
    echo "Skipping all tests."
    exit 0
fi


echo "[+] Checking /etc/hosts for splunk entry..."
if ping -c1 splunk; then
    echo "   ✓ Splunk host reachable"
else
    echo "   ✗ Splunk host unreachable or does not exist"
    exit 1
fi
echo

echo "[+] Checking Docker daemon configuration..."
if [ -f /etc/docker/daemon.json ]; then
    if grep -q '"splunk-url": "http://splunk:8088"' /etc/docker/daemon.json; then
        echo "   ✓ Docker daemon configured with correct Splunk URL"
    else
        echo "   ✗ Docker daemon NOT configured with correct Splunk URL"
        echo "   Current splunk-url:"
        grep "splunk-url" /etc/docker/daemon.json || echo "   Not found"
    fi
else
    echo "   ✗ Docker daemon configuration not found"
    exit 1
fi
echo

echo "[+] Testing connectivity to Splunk HEC..."
# Test if we can reach Splunk HEC
if curl -s -o /dev/null -w "%{http_code}" \
       -H "Authorization: Splunk 11111111-1111-1111-1111-111111111111" \
       http://splunk:8088/services/collector/health | grep -q "200"; then
    echo "   ✓ Successfully connected to Splunk HEC"
else
    echo "   ✗ Failed to connect to Splunk HEC"
    exit 1
fi
echo

echo "[+] Testing Docker logging and verifying in Splunk..."
TEST_MESSAGE="TEST_LOG_FROM_NODE_${WORKSPACE_NODE}_ID_$$"

echo "   Creating test container splunk-test-$$"
docker run --rm -d --name splunk-test-$$ alpine:latest sh -c "
    echo '${TEST_MESSAGE}';
    echo 'Log line 1 from node ${WORKSPACE_NODE}'; sleep 0.5;
    echo 'Log line 2 from node ${WORKSPACE_NODE}'; sleep 0.5;
    echo 'Log line 3 from node ${WORKSPACE_NODE}'; sleep 0.5;
    echo 'Log line 4 from node ${WORKSPACE_NODE}'; sleep 0.5;
" || {
    echo "   ✗ Failed to create test container"
    exit 1
}

# Wait for container to finish and logs to be ingested
echo "   Waiting for container to finish and logs to be ingested..."
docker wait splunk-test-$$

# Give Splunk a moment to ingest the logs
sleep 2

echo "   Searching Splunk for test logs..."

# Query Splunk for our test message
# Using Splunk REST API to search for our test message
SEARCH_QUERY="search ${TEST_MESSAGE}"
ENCODED_QUERY=$(echo -n "$SEARCH_QUERY" | jq -sRr @uri)

# Execute search job
# Note: Splunk management API uses HTTPS on port 8089!
SEARCH_RESPONSE=$(curl -s -k \
    -u "admin:DojoSplunk2024!" \
    -d "search=${SEARCH_QUERY}" \
    -d "earliest_time=-5m" \
    -d "latest_time=now" \
    -d "output_mode=json" \
    "https://splunk:8089/services/search/jobs/export" || echo "{}")

# Check if we found our test message
if echo "$SEARCH_RESPONSE" | grep -q "$TEST_MESSAGE"; then
    echo "   ✓ Test logs found in Splunk!"
    echo "   Found $(echo "$SEARCH_RESPONSE" | grep -c "$TEST_MESSAGE") occurrence(s)"
else
    echo "   ⚠ Could not verify logs in Splunk (may need more time to index)"
    echo "   Note: Logs may still be processing. Check Splunk UI at http://<host>:8001"
    echo "   Search for: ${TEST_MESSAGE}"
    exit 1
fi

# Also test if container logs are being forwarded
echo
echo "[+] Checking Docker container log forwarding..."

# Look for any docker container logs in Splunk
CONTAINER_SEARCH="search source=\"stderr\" OR source=\"stdout\" | head 5"
CONTAINER_LOGS=$(curl -s -k \
    -u "admin:DojoSplunk2024!" \
    -d "search=${CONTAINER_SEARCH}" \
    -d "earliest_time=-5m" \
    -d "latest_time=now" \
    -d "output_mode=json" \
    "https://splunk:8089/services/search/jobs/export" 2>/dev/null || echo "{}")

if [ ! -z "$CONTAINER_LOGS" ] && [ "$CONTAINER_LOGS" != "{}" ]; then
    echo "   ✓ Found Docker container logs in Splunk"
else
    echo "   ⚠ No recent Docker container logs found (may be normal if no containers running)"
    exit 1
fi
echo

echo
echo "[+] Checking systemd journal log forwarding..."

# Generate a unique test message in the journal
TEST_JOURNAL_MSG="JOURNAL_TEST_NODE_${WORKSPACE_NODE}_$$"
echo "   Writing test message to journal: ${TEST_JOURNAL_MSG}"
echo "$TEST_JOURNAL_MSG" | systemd-cat -t splunk-test -p info

# Give Splunk time to receive and index the journal entry
sleep 3

# Search for the journal test message
JOURNAL_SEARCH="search source=\"systemd-journal\" ${TEST_JOURNAL_MSG}"
JOURNAL_RESPONSE=$(curl -s -k \
    -u "admin:DojoSplunk2024!" \
    -d "search=${JOURNAL_SEARCH}" \
    -d "earliest_time=-5m" \
    -d "latest_time=now" \
    -d "output_mode=json" \
    "https://splunk:8089/services/search/jobs/export" || echo "{}")

if echo "$JOURNAL_RESPONSE" | grep -q "$TEST_JOURNAL_MSG"; then
    echo "   ✓ Systemd journal logs found in Splunk!"
else
    echo "   ⚠ Could not find systemd journal logs in Splunk"
    echo "   Note: Journal forwarding service may not be running yet"
    
    # Check if the service is running
    if systemctl is-active journal-to-splunk.service >/dev/null 2>&1; then
        echo "   ✓ journal-to-splunk.service is active"
    else
        echo "   ✗ journal-to-splunk.service is not active"
        echo "   Run: systemctl status journal-to-splunk.service"
    fi
fi

echo "=== Test Succeeded ==="
