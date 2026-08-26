---
name: run-tests
description: Run dojo tests, analyze failures, and debug issues. Use when testing code changes, running pytest, verifying fixes, or debugging test failures.
---

# Running Tests

Tests take ~10 minutes to run, so run them as a background process.

## Running All Tests

Start tests in background:
```bash
./deploy.sh -b -t 2>&1 | tee /tmp/test.log &
```

Monitor progress:
```bash
tail -f /tmp/test.log
```

## Running Specific Tests

Pass a pytest expression through the deployment helper:

```bash
./deploy.sh -N -t -k test_create_dojo 2>&1 | tee /tmp/test.log &
```

Start the DOJO with `./deploy.sh -b` first if an instance is not already running.

## Analyzing Failures

After tests complete, analyze `/tmp/test.log`:
1. Search for `FAILED` to find failing tests
2. Search for `ERROR` to find errors
3. Look at the full traceback for each failure

## Debugging Workflow

1. **Identify failures** - Analyze `/tmp/test.log` for FAILED/ERROR
2. **Find root cause** - Look at tracebacks, check CTFd logs with:
   ```bash
   docker exec "$(basename "$PWD")" journalctl -b -u dojo-ctfd --no-pager
   ```
   Inspect all native services with `systemctl status dojo.target` and `systemctl --failed` inside the outer container.
3. **If root cause unclear** - Add logging to help understand, then rerun tests
4. **Fix the root cause** - Don't just fix symptoms
5. **Run specific tests** - Pass a `-k` expression to `./deploy.sh -N -t`
6. **Verify fix** - Ensure the specific test passes
7. **Run ALL tests** - Run the full suite before declaring success

## Key Commands

```bash
# Start all tests (background)
./deploy.sh -b -t 2>&1 | tee /tmp/test.log &

# Check if tests are still running
jobs

# View test output
cat /tmp/test.log

# Search for failures
rg "FAILED|ERROR|error" /tmp/test.log

# View CTFd logs for debugging
docker exec "$(basename "$PWD")" journalctl -b -u dojo-ctfd --no-pager

# Run DB queries for debugging
docker exec -i "$(basename "$PWD")" dojo db
```

## Multinode Testing

After all singlenode tests pass, run multinode tests to verify the full cluster setup:

```bash
./deploy.sh -b -M -t 2>&1 | tee /tmp/test-multinode.log &
```

Monitor progress:
```bash
tail -f /tmp/test-multinode.log
```

Multinode mode starts 3 containers (1 main + 2 workspace nodes) and tests the distributed architecture. Some things that only run on the main node (like stats-worker) need special handling in multinode.

## Critical Reminder

**ALWAYS rerun all singlenode tests before declaring everything passed.** Fixing one test can break others.

**After singlenode tests pass, run multinode tests (`-M` flag) to verify the full cluster setup works correctly.**
