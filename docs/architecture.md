# DOJO Architecture

The pwn.college DOJO provides hands-on cybersecurity challenges without requiring learners to configure local environments. It extends [CTFd](https://github.com/CTFd/CTFd) with browser and SSH workspaces, challenge lifecycle management, persistent homes, and instructor-facing course features.

Learner workspaces are isolated Docker containers. A workspace starts when a learner begins a challenge and stops when the learner is finished or its timeout expires. Browser services such as VSCode and the desktop run inside that workspace, while a standard suite of security tools is mounted into every challenge environment.

The challenge objective is always to capture a flag. The learner runs as `hacker` (UID 1000), while `/flag` is readable only by `root` (UID 0). A root-owned setuid challenge program can read the flag, and the learner must satisfy or exploit that program to obtain it.

## Infrastructure Layout

The repository's root flake builds a NixOS root filesystem archive through the `.#dojo-image` output. The archive is imported as a Docker image with `/init` as its command. That produces a privileged outer container with systemd as PID 1.

Infrastructure processes run as native NixOS services inside the outer container. The Docker daemon inside that container is reserved for learner challenge and workspace containers.

```text
DOJO host
└── Host Docker daemon
    └── Privileged NixOS outer container
        ├── systemd
        │   ├── CTFd and background workers
        │   ├── PostgreSQL, PgBouncer, and Redis
        │   ├── nginx and OpenSSH
        │   ├── homefs and dojofs
        │   └── workspace and frontend builders
        └── Inner Docker daemon
            └── Learner challenge containers
```

The outer container remains a useful deployment boundary: the host only needs Docker and Nix to build it, while NixOS defines the complete runtime and service dependencies. Privileged mode is required for the inner Docker daemon, shared mounts, network setup, and filesystem services.

## Native Services

The NixOS modules under [`nix/`](../nix) declare the infrastructure. The principal units are:

- `dojo-ctfd.service`
- `dojo-nginx.service`
- `sshd.service`
- `dojo-stats-worker.service`
- `dojo-image-pull-worker.service`
- `dojo-homefs.service`
- `dojo-dojofs.service`
- `dojo-frontend.service`
- `dojo-workspace-builder.service`

`dojo.target` groups the runtime services. `dojo-ready.target` represents a fully initialized node, and `dojo wait` is the supported readiness interface for deployment and tests.

## Administrative Commands

The repository provides three primary command interfaces:

- [`dojo-config`](../dojo/dojo-config) creates persistent and runtime configuration.
- [`dojo`](../dojo/dojo) provides database, Flask, workspace, backup, restore, log, and readiness operations.
- [`dojo-node`](../dojo/dojo-node) configures WireGuard relationships between the main node and workspace nodes.

Systemd starts initialization and the units required by the node's role. Timers handle periodic work such as database backups, cache refreshes, and challenge-container maintenance.

## Configuration and Data

Persistent state is mounted at `/data`. Important paths include:

- `/data/config.env` for administrator configuration
- `/data/postgres` for PostgreSQL data
- `/data/redis` for Redis data
- `/data/dojos` for dojo definitions
- `/data/homes` for learner home subvolumes
- `/data/workspace/nix` for the workspace Nix store
- `/data/docker` for the inner Docker daemon
- `/data/workspace_nodes.json` for multi-node configuration

`dojo-config` creates defaults when persistent configuration does not exist. Environment variables supplied to the outer container override or seed those values. It writes the complete durable configuration to root-only `/data/config.env`, keeps a root-only runtime copy at `/run/dojo/config.env`, and derives narrower environment files for the individual services that need them.

## CTFd and the DOJO Plugin

The user-facing application is a CTFd plugin in [`dojo_plugin/`](../dojo_plugin), paired with the theme and templates in [`dojo_theme/`](../dojo_theme). Together they replace most of the stock CTFd interface and implement dojo, module, challenge, workspace, scoreboard, and administrative behavior.

CTFd accesses PostgreSQL through SQLAlchemy and coordinates transient state through Redis. The native CTFd service can access the inner Docker socket directly, allowing it to start and manage learner containers without another infrastructure-container boundary.

Use `dojo flask` for a Python shell in the configured CTFd environment and `dojo db` for a database client.

## Challenge Containers

When a learner launches a challenge, CTFd creates a container through the inner Docker daemon and:

- copies challenge files into the container;
- mounts the standard workspace tool environment;
- mounts the learner's persistent home directory;
- applies the configured network and security policy; and
- starts any requested browser workspace services.

The workspace initializer ensures the `hacker` user and standard filesystem interfaces exist, installs the flag, and runs challenge initialization. Challenge containers use a six-hour lifetime by default.

## Workspace Tools

The workspace builder realizes the Nix tool environment under `/data/workspace/nix`. Challenge containers receive a read-only `/nix` mount and a profile exposed through `/run/dojo`.

The dojofs service provides the filtered filesystem view used to keep ordinary challenge processes separate from privileged workspace tooling. This allows all challenges to share a consistent tool suite without baking those tools into every challenge image.

## Persistent Homes

Learner homes are btrfs subvolumes under `/data/homes`, with a per-user quota. The native homefs service exposes a Docker volume plugin socket to the inner daemon. When CTFd starts a challenge, its `homefs` volume request causes Docker to mount the correct learner subvolume into the container.

The `/data` mount must use shared propagation so mounts created inside the outer container are visible where Docker expects them.

## Workspace Access

HTTP workspace traffic enters through the native nginx service. CTFd authorizes the request and routes it to the selected learner container. Workspace services are started on demand when the corresponding browser endpoint is requested.

SSH access is handled by the native OpenSSH service. It validates the submitted public key against the DOJO database, resolves the learner and active workspace, then enters that workspace through the inner Docker daemon.

## Multi-node Operation

A main node runs the application, database, public proxy, and coordination services. Workspace nodes run the storage, Docker, and workspace services needed to host learner containers. `dojo-node` manages the WireGuard keys and the ordered node list stored in `/data/workspace_nodes.json`.

Each node has distinct persistent data and Docker storage. Nodes share a `WORKSPACE_SECRET`; workspace nodes also receive the main node's public `WORKSPACE_KEY`, reachable `DOJO_HOST` and `STORAGE_HOST` values, and the public `WORKSPACE_HOST`. The main proxy sends authorized workspace traffic to the selected node over WireGuard, so workspace nodes do not expose separate learner-facing hosts or certificates.

## Logs and Diagnostics

All infrastructure logs are available through the outer container's journal:

```sh
docker exec dojo systemctl --failed
docker exec dojo systemctl status dojo.target
docker exec dojo journalctl -b -u dojo-ctfd
docker exec dojo journalctl -b -u dojo-nginx
docker exec dojo journalctl -b -u docker
```

Use `docker logs dojo` for messages emitted before or outside the journal, and `docker exec dojo dojo wait` to test the same readiness condition used by deployment and CI.
