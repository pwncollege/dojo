# Background Stats Testing Documentation

## Overview

This document describes the integration test suite for the Phase 1 background stats implementation. The tests verify that the event-driven stats system works correctly, including Redis Stream event publishing, background worker processing, and cache operations.

## Test Files

### `test_background_stats.py` - Integration Tests

Integration tests that verify the entire background stats system working together with the dojo infrastructure.

#### Test Categories:

**Event Publishing Tests:**
- `test_redis_stream_event_published` - Verifies that solve events are published to Redis Stream
- `test_redis_stream_cleanup` - Tests Redis Stream event storage

**Worker Processing Tests:**
- `test_background_worker_processes_events` - Verifies worker consumes events and updates cache
- `test_multiple_solves_update_stats` - Tests that stats are recalculated on multiple solves
- `test_concurrent_solves` - Tests handling of concurrent solve events from multiple users

**Cache Tests:**
- `test_stats_api_reads_from_cache` - Verifies web workers read from Redis cache
- `test_cache_timestamps` - Tests that cache timestamps are properly set
- `test_cache_structure` - Validates the structure of cached stats data

**Cold Start Tests:**
- `test_cold_start_initializes_cache` - Tests worker initialization populates cache

**Data Validation Tests:**
- `test_recent_solves_appear_in_stats` - Verifies recent solves are tracked
- `test_chart_data_structure` - Validates chart data format
- `test_stats_consistency_after_multiple_updates` - Tests data consistency

**Infrastructure Tests:**
- `test_stats_worker_running` - Checks that stats-worker container is running
- `test_worker_env_variables` - Validates worker environment configuration

**Fallback Tests:**
- `test_fallback_calculation_when_cache_miss` - Tests synchronous fallback on cache miss

## Running the Tests

### Run All Background Stats Tests

```bash
# Restart dojo and run all tests
./deploy.sh -t

# Run only background stats tests
docker run -v /var/run/docker.sock:/var/run/docker.sock \
  -v $PWD:/opt/pwn.college \
  -e "DOJO_CONTAINER=dojo" \
  dojo-test pytest -v \
  /opt/pwn.college/test/test_background_stats.py
```

### Run Specific Test

```bash
docker run -v /var/run/docker.sock:/var/run/docker.sock \
  -v $PWD:/opt/pwn.college \
  -e "DOJO_CONTAINER=dojo" \
  dojo-test pytest -v \
  /opt/pwn.college/test/test_background_stats.py::test_redis_stream_event_published
```

### Run Without Restarting Dojo

```bash
# Run tests on existing dojo instance
./deploy.sh -N -t
```

## Test Fixtures

### `stats_test_dojo`
- Creates a fresh test dojo with cleared Redis cache
- Used for most integration tests

### `stats_test_user`
- Creates a random user with session
- Used for solve-based tests

### Helper Functions

**`get_redis_client()`**
- Returns a Redis client connected to the cache

**`clear_redis_stats()`**
- Clears all stats-related Redis keys
- Used to ensure clean test state

**`wait_for_cache_update(dojo_id, timeout=10)`**
- Waits for cache to be updated by worker
- Returns True if cache appears within timeout

**`get_stream_length()`**
- Returns the number of events in Redis Stream

## Test Coverage

The integration test suite covers:

1. **Event Flow**: Solve → Event → Worker → Cache → Web Request
2. **Cache Operations**: Read, Write, Update, Timestamp
3. **Concurrency**: Multiple users, multiple solves
4. **Cold Start**: Worker initialization on startup
5. **Fallback**: Synchronous calculation when cache unavailable
6. **Data Integrity**: Stats accuracy, structure validation
7. **Infrastructure**: Worker running, environment configuration

## Expected Behavior

### Normal Operation
1. User solves challenge
2. SQLAlchemy event listener fires
3. Event published to Redis Stream (`stat:events`)
4. Background worker consumes event
5. Worker calculates fresh stats
6. Worker stores in Redis cache (`stats:dojo:{dojo_id}`)
7. Next web request reads from cache (fast!)

### Fallback Operation
1. User requests stats
2. Check Redis cache
3. **If cache miss and BACKGROUND_STATS_FALLBACK=1:**
   - Calculate synchronously
   - Return result
4. **If cache miss and BACKGROUND_STATS_FALLBACK=0:**
   - Return empty/default stats

## Debugging Failed Tests

### Test fails with "Cache was not updated within timeout"
- Check if stats-worker container is running: `docker ps | grep stats-worker`
- Check worker logs: `docker logs stats-worker`
- Increase timeout in test
- Check Redis connectivity

### Test fails with "stats-worker container not found"
- Worker not in docker-compose or not started
- Check docker-compose.yml has stats-worker service
- Ensure `./deploy.sh` starts all services

### Test fails with Redis connection errors
- Check Redis container is running: `docker ps | grep cache`
- Check Redis connectivity from test container
- Verify REDIS_URL environment variable

### Stats calculation mismatch
- Check database has expected data
- Verify calculation logic in `calculate_dojo_stats()`
- Check for race conditions with concurrent tests

## Adding New Tests

When adding new stat types (Phase 2+), follow this pattern:

1. Add integration tests in `test_background_stats.py`
   - Test event publishing
   - Test worker processing
   - Test cache updates
   - Test API reads from cache

2. Use fixtures for consistency
   - Reuse `stats_test_dojo` and `stats_test_user`
   - Add new fixtures if needed

## Performance Considerations

- Tests use `time.sleep()` to wait for async operations
- Adjust timeouts based on CI/CD environment
- Some tests may be slow due to worker processing lag
- Consider parallelizing independent tests

## Future Test Additions

For subsequent phases, add tests for:

**Phase 2 (Scoreboard):**
- Scoreboard cache updates
- Ranking accuracy
- Multiple duration filters

**Phase 3 (Scores):**
- Dojo rankings
- Module rankings
- Score calculation

**Phase 4 (Belts & Emojis):**
- Belt data caching
- Emoji per-user caching
- Award event processing

**Phase 5 (Advanced):**
- Priority queue handling
- Batch processing
- Event deduplication
- Monitoring metrics
