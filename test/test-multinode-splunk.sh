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

if [ "${WORKSPACE_NODE}" -eq 0 ]; then
    SPLUNK_HOST=127.0.0.1
else
    SPLUNK_HOST=192.168.42.1
fi

SPLUNK_HEC_URL="http://${SPLUNK_HOST}:8088"
SPLUNK_MANAGEMENT_URL="https://${SPLUNK_HOST}:8089"

search_splunk() {
    curl --fail-with-body --silent --show-error --insecure \
        --connect-timeout 5 --max-time 30 \
        -u "admin:DojoSplunk2024!" \
        -d "search=$1" \
        -d "earliest_time=-5m" \
        -d "latest_time=now" \
        -d "output_mode=json" \
        "${SPLUNK_MANAGEMENT_URL}/services/search/jobs/export"
}

echo "[+] Checking generated Docker daemon configuration..."
if [ -f /run/dojo/docker-daemon.json ]; then
    DOCKER_SPLUNK_URL=$(jq -r '.["log-opts"]["splunk-url"] // empty' /run/dojo/docker-daemon.json)
    if [ "${DOCKER_SPLUNK_URL}" = "${SPLUNK_HEC_URL}" ]; then
        echo "   ✓ Docker daemon configured with correct Splunk URL"
    else
        echo "   ✗ Docker daemon NOT configured with correct Splunk URL"
        echo "   Expected: ${SPLUNK_HEC_URL}"
        echo "   Actual: ${DOCKER_SPLUNK_URL:-not found}"
        exit 1
    fi
else
    echo "   ✗ Docker daemon configuration not found"
    exit 1
fi
echo

echo "[+] Testing connectivity to Splunk HEC..."
# Test if we can reach Splunk HEC
if curl --fail --silent --show-error --connect-timeout 5 --max-time 30 -o /dev/null \
       -H "Authorization: Splunk 11111111-1111-1111-1111-111111111111" \
       "${SPLUNK_HEC_URL}/services/collector/health"; then
    echo "   ✓ Successfully connected to Splunk HEC"
else
    echo "   ✗ Failed to connect to Splunk HEC"
    exit 1
fi
echo

echo "[+] Testing Docker logging and verifying in Splunk..."
TEST_MESSAGE="TEST_LOG_FROM_NODE_${WORKSPACE_NODE}_ID_$$"

echo "   Creating test container splunk-test-$$"
docker run --rm -d --name splunk-test-$$ busybox:uclibc sh -c "
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

echo "   Searching Splunk for test logs..."

SEARCH_QUERY="search ${TEST_MESSAGE}"
SEARCH_FOUND=no
for _ in {1..15}; do
    sleep 2
    if SEARCH_RESPONSE="$(search_splunk "$SEARCH_QUERY")" &&
        jq -e --arg message "$TEST_MESSAGE" \
            'select((.result._raw? // "") | contains($message))' \
            <<< "$SEARCH_RESPONSE" >/dev/null; then
        SEARCH_FOUND=yes
        break
    fi
done

if [ "$SEARCH_FOUND" = yes ]; then
    echo "   ✓ Test logs found in Splunk!"
    echo "   Found $(echo "$SEARCH_RESPONSE" | grep -c "$TEST_MESSAGE") occurrence(s)"
else
    echo "   ✗ Could not verify logs in Splunk"
    exit 1
fi

echo
echo "[+] Checking systemd journal log forwarding..."
TEST_JOURNAL_MESSAGE="JOURNAL_TEST_NODE_${WORKSPACE_NODE}_$$"
echo "${TEST_JOURNAL_MESSAGE}" | systemd-cat --identifier=dojo-splunk-test --priority=info

JOURNAL_FOUND=no
for _ in {1..15}; do
    sleep 2
    JOURNAL_SEARCH="search source=\"systemd-journal\" ${TEST_JOURNAL_MESSAGE}"
    if JOURNAL_RESPONSE="$(search_splunk "$JOURNAL_SEARCH")" &&
        jq -e --arg message "$TEST_JOURNAL_MESSAGE" \
            'select((.result._raw? // "") | contains($message))' \
            <<< "$JOURNAL_RESPONSE" >/dev/null; then
        JOURNAL_FOUND=yes
        break
    fi
done

if [ "${JOURNAL_FOUND}" = yes ]; then
    echo "   ✓ Systemd journal logs found in Splunk!"
else
    echo "   ✗ Could not find systemd journal logs in Splunk"
    systemctl status dojo-journal-splunk.service --no-pager || true
    exit 1
fi

echo "=== Test Succeeded ==="
