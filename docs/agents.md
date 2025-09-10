# AGENTS

This file provides guidance to AI agents when working with code in this repository.

## Overview

The pwn.college DOJO is a cybersecurity education platform built as a comprehensive CTFd plugin.
It provides isolated Docker-based workspace environments for hands-on security challenges.
The DOJO runs in a docker-in-docker setting, with the "outer" container using docker-compose to spin up "inner" containers running infrastructure components.

## Common Development Commands

### Quick Development Setup

```bash
# Start up the dojo
./deploy.sh

# (Re)start the dojo, and run all testcases
./deploy.sh -t

# Run the testcases (without restarting the dojo)
./deploy.sh -N -t

# Get container details
DOJO_CONTAINER=$(basename "$PWD")

# access the web instance
DOJO_IP=$(docker inspect "$DOJO_CONTAINER" | jq -r '.[0].NetworkSettings.Networks.bridge.IPAddress')
curl "http://$DOJO_URL"

# get CTFd logs
docker exec "$DOJO_CONTAINER" docker logs ctfd

# interact with docker-compose with the correct settings
docker exec "$DOJO_CONTAINER" dojo compose ps

# interact with docker-compose with the correct settings
docker exec "$DOJO_CONTAINER" dojo compose ps

# run DB queries against DOJO's postgresql database
docker exec -i "$DOJO_CONTAINER" dojo db

# run python in the DOJO's CTFd context
docker exec -i "$DOJO_CONTAINER" dojo flask

# enter a learner's container (must be started first via a testcase or the web interface)
docker exec -i "$DOJO_CONTAINER" dojo enter USER_ID

# run an inidividual testcase (needs docker socket)
docker run -v /var/run/docker.sock:/var/run/docker.sock -v $PWD:/opt/pwn.college -e "DOJO_CONTAINER=dojo" dojo-test pytest -v /opt/pwn.college/test/test_dojos.py::test_create_dojo
```

### Troubleshooting

Container start failures show up in the ctfd container logs.

### Testing

```bash
# Restart the dojo and run all tests
./deploy.sh -t

# Run the testcases again (without restarting the dojo)
./deploy.sh -N -t

# Run tests without using docker or workspace cache
./deploy.sh -D "" -W "" -t

# Run an individual testcase (needs docker socket)
docker run -v /var/run/docker.sock:/var/run/docker.sock -v $PWD:/opt/pwn.college -e "DOJO_CONTAINER=dojo" dojo-test pytest -v /opt/pwn.college/test/test_dojos.py::test_create_dojo
```

**Test Script Options:**
- `-r DB_BACKUP`: Restore database backup before testing
- `-c CONTAINER_NAME`: Custom container name (default: <dirname>)
- `-D DOCKER_DIR`: Persistent Docker directory (avoids rebuilds)
- `-W WORKSPACE_DIR`: Persistent workspace directory (avoids rebuilds)
- `-T`: Skip running tests (only setup environment)
- `-N`: Skip startup (just run tests)
- `-p`: Export ports (80->80, 443->443, 22->2222)
- `-e ENV_VAR=value`: Set environment variables
- `-b`: Build Docker image locally


## High-Level Architecture

### Nested Docker Architecture
The system uses a sophisticated nested Docker setup:
- Outer container runs all infrastructure (CTFd, database, nginx, etc.)
- Inner Docker-in-Docker daemon manages isolated user workspace containers
- This provides strong security isolation between infrastructure and user environments

### Key Components

1. **CTFd Plugin** (`/dojo_plugin/`)
   - Core application logic as CTFd plugin
   - API endpoints in `api/`
   - Database models in `models/`
   - Page controllers in `pages/`

2. **Theme** (`/dojo_theme/`)
   - Custom UI replacing most CTFd frontend
   - Static assets in `static/`
   - Templates in `templates/`

3. **Workspace** (`/workspace/`)
   - Nix-based tool provisioning
   - User container configuration
   - Security tools and development environment

4. **SSH Service** (`/sshd/`)
   - Custom SSH daemon for user access
   - Authenticates against database
   - Executes into user containers

### Data Storage

Inside the "outer" component:

- `/data/` - All persistent data
- `/data/homes/` - User home directories (btrfs subvolumes, 1GB limit)
- `/data/dojos/` - Dojo challenge definitions
- `/data/workspace/nix/` - Nix store for tools
- `/data/postgres/` - Database files

### Container Services
The docker-compose.yml defines these services:
- `db` - PostgreSQL database
- `cache` - Redis cache
- `ctfd` - Main CTFd application
- `nginx` - Reverse proxy with SSL
- `sshd` - SSH access service
- `homefs` - Home directory management
- `workspacefs` - Workspace filesystem overlay
- Monitoring stack (Prometheus, Grafana, Splunk)

### Security Model
- Challenges run as setuid binaries
- Flag at `/flag` readable only by root
- User runs as `hacker` (UID 1000)
- Custom seccomp profiles for containers
- Network isolation between user containers

### Workspace Environment
- Tools provided via Nix overlay at `/nix`
- Mounted in `/run/dojo/` inside user containers
- On-demand services: VSCode (`code`), Desktop (`desktop`), ttyd (`terminal`)
- 6-hour timeout for idle containers

## Adding Configuration

To add a new configuration entry:
1. Add default in `dojo/dojo-init`
2. Propagate to containers in `docker-compose.sh`
3. Load as global in `dojo_plugin/config.py`
4. Import where needed

## Testing Approach

The project uses pytest with fixtures for:
- User session management
- Dojo creation and loading
- Challenge interaction testing

Run tests with `./deploy.sh -t` which handles container setup and cleanup.
Tests are in `test/test_*.py`, implemented as module-level `test_*` functions, not classes.

## Coding Standards

### Comments and Documentation

**DO NOT ADD COMMENTS.**

Comments are only acceptable when they explain non-obvious **why** decisions, complex algorithms, or critical business rules that cannot be understood from the code itself.

Examples of unacceptable comments:
```python
# DON'T DO THIS
# Generate RSA key
# Get user by ID
# Increment counter
# Call the function
```

The only acceptable comments explain critical context that cannot be inferred:
```python
# Exponential penalty: each attempt reduces score by 10%
base_score = 100 * (0.9 ** attempts)

# Docker socket must be mounted at this exact path for Mac compatibility
SOCKET_PATH = "/var/run/docker.sock"
```

Function and variable names must be self-documenting. If you feel the need to add a comment, first consider if better naming would make it unnecessary.
