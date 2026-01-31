# Background Container Start

## Overview

Move the blocking `start_challenge()` work out of Gunicorn web workers and into a dedicated background service. The POST /docker endpoint returns immediately with a `start_id`, and a separate `container-worker` service processes the actual Docker container lifecycle. The frontend polls a new status endpoint until the container is ready.

## Goals

- Free Gunicorn workers immediately after request validation so browsing users are unaffected during thundering-herd container starts (e.g., start of class)
- Provide visible progress feedback to users during container startup
- Enable horizontal scaling of container start capacity independently of web workers

## Non-Goals / Out of Scope

- Moving initialization logic (`.init`, file injection) into the workspace container itself (that's a separate future effort per issue #1025 discussion)
- Changing the React frontend (future.pwn.college) — only the production jQuery frontend (dojo_theme) is in scope
- Global rate limiting or priority queues — the worker pool size is the natural concurrency limit
- Changing how container teardown (DELETE /docker) works — it stays synchronous (fast operation)

## Design

### Architecture

```
Frontend (jQuery)
    |
    | POST /docker  (returns immediately with start_id)
    v
Gunicorn Web Worker
    |
    | 1. Validate request (auth, dojo access, challenge visibility, locks)
    | 2. Acquire per-user Redis lock
    | 3. Generate start_id (UUID)
    | 4. Write initial status to Redis: container_start:{start_id} = {status: "queued", attempt: 0}
    | 5. Publish to Redis Stream: container:starts
    | 6. Return {success: true, start_id: "..."}
    v
Redis Stream (container:starts)
    |
    | Consumer group: container-workers
    v
container-worker service (N child processes via multiprocessing)
    |
    | 1. Consume message from stream
    | 2. Re-query User + DojoChallenges from DB using composite PK
    | 3. Update Redis status: "starting", attempt: 1
    | 4. Call start_challenge() (existing function, moved here)
    | 5. On success: status = "ready", release per-user lock
    | 6. On failure: retry up to 3 times, then status = "failed", release lock
    | 7. ACK message in stream
    v
Frontend polls GET /docker/status?id={start_id}
    |
    | Returns: {status, attempt, error}
    | Frontend polls every 2 seconds
    | 5-minute client-side timeout
```

### New Docker-Compose Service

A new `container-worker` service, following the same pattern as `stats-worker`:

- Uses `<<: *ctfd-base` for image, volumes, Docker socket access
- Runs via `flask shell` for full Flask app context (DB, config, SECRET_KEY)
- Single container that spawns N child processes internally via `multiprocessing`
- Default N=8 (matches Gunicorn worker count), configurable via `CONTAINER_WORKERS` env var
- Each child process is an independent Redis Stream consumer in the `container-workers` consumer group

### Redis Stream Message Format

Stream name: `container:starts`

Message payload (JSON):
```json
{
  "start_id": "uuid-string",
  "user_id": 123,
  "dojo_id": 456,
  "module_index": 0,
  "challenge_index": 2,
  "practice": false,
  "as_user_id": null
}
```

Fields use the composite primary key for DojoChallenges: `(dojo_id, module_index, challenge_index)`. NOT `DojoChallenges.id` (string slug) or `DojoChallenges.challenge_id` (FK to CTFd Challenges table).

### Redis Status Key

Key: `container_start:{start_id}`
TTL: 1 hour
Value (JSON):
```json
{
  "status": "queued|starting|initialized|ready|failed",
  "attempt": 0,
  "max_attempts": 3,
  "error": null,
  "user_id": 123
}
```

Status progression: `queued` → `starting` → `initialized` → `ready`
On failure after all retries: `failed` with error message.

The `initialized` status maps to the existing `DOJO_INIT_INITIALIZED` log signal (container is up, challenge/flag not yet inserted). This gives the frontend a meaningful intermediate state.

### API Changes

**POST /api/v1/docker** (modified)

Request body: unchanged.

Response (new):
```json
{"success": true, "start_id": "uuid-here"}
```

The endpoint no longer blocks. It validates, acquires lock, enqueues, and returns.

**GET /api/v1/docker/status** (new)

Query param: `id` (the start_id from POST)

Response:
```json
{
  "success": true,
  "status": "starting",
  "attempt": 2,
  "max_attempts": 3,
  "error": null
}
```

This endpoint reads from Redis only — no DB or Docker calls. Very fast.

**GET /api/v1/docker** and **DELETE /api/v1/docker**: unchanged.

### Per-User Locking

The existing `docker_locked` decorator acquires a per-user Redis lock in the web request. The lock timeout should be generous (120 seconds) as a crash safety net. The worker explicitly releases the lock when it writes a terminal status (`ready` or `failed`) to the Redis status key. If the worker crashes, Redis Streams pending entry logic lets another worker claim the message, and the lock auto-releases after timeout.

### Frontend Changes

In `dojo_theme/static/js/dojo/challenges.js`, the `startChallenge()` function (line 172):

1. POST to `/pwncollege_api/v1/docker` — returns immediately with `start_id`
2. Start polling `GET /pwncollege_api/v1/docker/status?id={start_id}` every 2 seconds
3. Update the "Loading..." message based on status:
   - `queued`: "Waiting to start..."
   - `starting`: "Starting challenge environment..." (show attempt N/3 if retrying)
   - `initialized`: "Initializing challenge..."
   - `ready`: proceed to load workspace (same as current success path)
   - `failed`: show error message (same as current error path)
4. Client-side timeout: 5 minutes. If still not `ready`/`failed`, show a timeout error with "try again".

### Worker Implementation

New files:
- `dojo_plugin/worker/container_worker.py` — main process manager, spawns N children
- `dojo_plugin/worker/container_start.py` — consumer loop + start_challenge execution

The worker child process loop:
1. XREADGROUP from `container:starts` stream, blocking with 5s timeout
2. Parse message, extract IDs
3. Re-query `User` and `DojoChallenges` from DB using primary keys
4. Update status to `starting`
5. Call `start_challenge(user, dojo_challenge, practice, as_user=as_user)`
6. On success: set status `ready`, release user lock, publish events (activity feed, stats)
7. On exception: increment attempt, retry (up to 3 times with 2s delays), then set `failed`
8. XACK the message

The `start_challenge()`, `start_container()`, `insert_challenge()`, `insert_flag()`, and `remove_container()` functions move from `docker.py` to a shared module importable by both the worker and (temporarily) the API. The POST handler in `docker.py` no longer calls these directly.

### Handling Stale/Crashed Workers

Redis Streams provides pending entry lists (PEL). If a consumer crashes mid-processing:
- The message stays in the PEL with no ACK
- Other consumers can claim it after a timeout using XAUTOCLAIM
- The worker should periodically XAUTOCLAIM messages pending for >60 seconds
- The per-user lock auto-releases after 120 seconds as a safety net

## Edge Cases & Failure Modes

**User clicks Start twice quickly:**
Per-user Redis lock prevents duplicate starts. Second POST gets "Already starting a challenge" error.

**Worker crashes mid-start:**
Message stays in Redis Stream PEL. Another worker claims it via XAUTOCLAIM after 60s. Lock auto-releases after 120s. Frontend's 5-minute timeout covers this window.

**All workers are busy:**
Messages queue in the Redis Stream. Users see `queued` status. Stream provides natural backpressure and FIFO ordering.

**Container start fails (Docker error, image pull failure, etc.):**
Worker retries 3 times with 2s delays. On final failure, sets status to `failed` with error message. Frontend shows the error.

**User navigates away during start:**
No cleanup needed. The worker finishes the start regardless. Container gets its normal 6-hour idle timeout. If user comes back, workspace is ready.

**Redis goes down:**
Status writes fail. Lock release fails. Frontend polling fails. Degrades similarly to current behavior — the feature depends on Redis just like the existing lock mechanism does.

**start_id collision:**
UUIDs. Effectively impossible.

**Worker re-queries DB and challenge no longer exists:**
Worker sets status to `failed` with an appropriate error. This is the TOCTOU gap we accepted by doing all validation in the web request. In practice the gap is milliseconds to seconds, and challenges don't get deleted during class.

## Anti-Patterns to Avoid

**Do not use threads in the gunicorn process.** The entire point is to move blocking Docker work out of the web worker processes. Threads in gunicorn still consume process resources and die on worker restarts.

**Do not re-validate permissions in the worker.** Validation happens in the web request where we have the authenticated user session. The worker trusts the enqueued message. Duplicating validation logic creates maintenance burden with no real benefit given the short queue times.

**Do not pass SQLAlchemy model objects through Redis.** Pass integer primary key fields only. Re-query in the worker. Be very careful with DojoChallenges — its PK is the composite `(dojo_id, module_index, challenge_index)`, NOT `id` (string slug) or `challenge_id` (FK to CTFd Challenges).

**Do not use Redis Pub/Sub for the queue.** Messages are lost if no consumer is listening. Redis Streams with consumer groups provide persistence, acknowledgment, and retry semantics.

**Do not use docker-compose scale for worker replicas.** Use a single service with internal multiprocessing. Simpler deployment, single log stream, configurable via env var.

## Open Questions

1. **Event publishing location:** The current POST handler publishes activity feed events and stats updates after successful container start (docker.py:495-508). These should move to the worker (after successful start_challenge). Confirm this doesn't break any assumptions about event timing relative to the HTTP response.

2. **Monitoring/observability:** Should we add Prometheus metrics for queue depth, wait time, start duration? The existing stats-worker has logging but no metrics endpoint.

3. **Graceful shutdown:** When the container-worker service restarts, in-progress container starts will be interrupted. XAUTOCLAIM handles message recovery, but the half-started container may need cleanup. The existing `remove_container()` at the start of `start_challenge()` already handles this (it removes any existing container before starting a new one).
