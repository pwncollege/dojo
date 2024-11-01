# DOJO Architecture

We created the pwn.college DOJO specifically to facilitate hands-on cybersecurity education.
DOJO adopts principles from the realm of Capture The Flag competitions, wherein learners are tasked with solving challenges and obtaining flags as evidence of their newfound skills.
Instead of imposing the onus of environment setup on learners, DOJO offers a pre-configured environment, available through browsers or SSH and allowing students to dive into hands-on cybersecurity challenges instantly.
In contrast to existing platforms, our primary focus is to allow students to execute _every step_---discovery, implementation, and debugging---of even the most advanced and technical challenges directly within the DOJO environment.

Of course, this all means that the DOJO is insanely complex, despite only comprising about 5,000 lines of actual code.
This document is an attempt to clarify this complexity and enable new admins or contributors to get up to speed quickly.

## High Level Overview

Roughly speaking, it is implemented as a "plugin" to the popular [CTFd](https://github.com/CTFd/CTFd) platform.
CTFd provides for a concept of users, challenges, and users solving those challenges by submitting flags.
The DOJO extends upon this by providing a way for instructors to create challenges, which students may then work on solving within a browser-based workspace environment.

These workspace environments are isolated from one another, and implemented as Docker containers (significantly more performant than deploying VMs).
The workspace starts when a student begins working on a challenge, and stops when the student is finished (or after a timeout).
It automatically spawns several services, including a VSCode instance, and desktop environment---both accessible within the browser via internal nginx redirects.
Alternatively, students may choose to connect to the workspace via SSH after providing an SSH public key in their profile settings.
Their home directory is persisted across workspace instances, allowing students to save their work and return to it later.
The workspace may also situationally start a virtual machine, if the challenge requires it (e.g., for kernel exploitation), or configure custom networking (e.g., for network exploitation).
Additionally, the workspace comes with a suite of tools pre-installed, including debuggers, disassemblers, and exploit development tools.

The challenge objective is always to *capture the flag*.
More specifically, the learner runs as the `hacker` user (UID 1000), and there is a flag file located at `/flag`, which is only readable by the `root` user (UID 0).
The challenge program runs as a root-owned setuid binary, and so it has the ability to read the flag.
The learner must then either satisfy some challenge requirements, or otherwise exploit the challenge program in order to *capture the flag*.

## Infrastructure Containerization

The DOJO components are managed by docker compose, configured [here](https://github.com/pwncollege/dojo/blob/master/docker-compose.yml).
Admins could conceivably launch this on a bare host, but we run our entire infra inside a docker container, defined [here](https://github.com/pwncollege/dojo/blob/master/Dockerfile).
We call this docker container the "outer docker".
Conceptually, this looks like:

```
-----------------------------------------------------
| The DOJO host                                     |
|                                                   |
|    - "Outer" Docker Daemon -                      |
|   /                         \                     |
|   ---------------------------------------------   |
|   | The "Outer Docker"                        |   |
|   |                                           |   |
|   |   Docker Compose                          |   |
|   |        |                                  |   |
|   |    - "Inner" Docker-in-Docker Daemon -    |   |
|   |   /                                  /    |   |
|   |   --------------------------------  /     |   |
|   |   |                              | /      |   |
|   |   |   ------------------------   |        |   |
|   |   |   | DOJO infra container |   |        |   |
|   |   |   ------------------------   |        |   |
|   |   |                              |        |   |
|   |   |   ------------------------   |        |   |
|   |   |   | DOJO infra container |   |        |   |
|   |   |   ------------------------   |        |   |
|   |   |                              |        |   |
|   |   |   ------------------------   |        |   |
|   |   |   | DOJO user container  |   |        |   |
|   |   |   ------------------------   |        |   |
|   |   |                              |        |   |
|   |   |   ------------------------   |        |   |
|   |   |   | DOJO infra container |   |        |   |
|   |   |   ------------------------   |        |   |
|   |   |                              |        |   |
|   |   --------------------------------        |   |
|   |                                           |   |
|   ---------------------------------------------   |
|                                                   |
-----------------------------------------------------
```

## DOJO Scripts

The dojo has a few scripts to help manage things:

- [dojo-init](https://github.com/pwncollege/dojo/blob/master/dojo/dojo-init) initializes the host and prepares it to run the dojo.
- [dojo](https://github.com/pwncollege/dojo/tree/master/dojo) provides functionality for admins to interact with the database (both in Python and via the DB client directly), user containers, and the dojo containers themselves.
- [dojo-node](https://github.com/pwncollege/dojo/blob/master/dojo/dojo-node) manages the dojo host's connection to its user hosting nodes. This is likely only used in the main https://pwn.college deployment.

## DOJO Startup

The outer docker initializes its environment with `dojo-init` and then runs `systemd`, which eventually calls `dojo up`.
A few [other systemd services](https://github.com/pwncollege/dojo/tree/master/etc/systemd/system) also exist:

- An hourly backup that dumps the dojo's main database into `/data/backups`.
- A service that syncs backups to the cloud.
- A service that runs every minute to refresh various redis caches to keep the front-end zippy.
- A service that runs every minute to refresh challenge containers on all dojo nodes.

## DOJO Configuration

Most of the configuration of the DOJO lives in two files:

### `/data/config.env`

This file is created in [dojo-init](https://github.com/pwncollege/dojo/blob/master/dojo/dojo-init#L30) if it does not already exist.
It controls a lot of different options.

### `/data/workspace_nodes.json`

This file is created by [dojo-node](https://github.com/pwncollege/dojo/blob/master/dojo/dojo-node#L36).
By default, it is an empty list.
The `dojo-node` script handles updating it with new nodes.
Each entry in this list is the node's wireguard public key.

## DOJO database

The DOJO uses mysql.

The DOJO database lives in the `db` container by default.
You can use an external database by setting `DB_HOST` in `config.env`.
To save resources, also set `DB_EXTERNAL` to `yes` so that the `db` container does not actually start mysql.

You can launch a database client session with `dojo db`.

## CTFd and the dojo-plugin

The front-end interface of the dojo is a total-conversion-style [CTFd plugin](https://github.com/pwncollege/dojo/tree/master/dojo_plugin).
The plugin, along with its companion [theme/templates](https://github.com/pwncollege/dojo/tree/master/dojo_theme) replaces almost all front-end functionality.

CTFd accesses the DOJO DB using the SQLAlchemy ORM.
You can drop into a python shell to leverage this as well by running `dojo flask`.

The docker socket of the docker-in-docker daemon is mapped into the CTFd container, allowing CTFd to start up user challenge containers.

## Challenge containers

When a user launches a challenge, CTFd starts a docker container that will run alongside the infrastructure containers, and:

- Copies challenge files into the container (currently [here](https://github.com/pwncollege/dojo/blob/master/dojo_plugin/api/v1/docker.py#L184)).
- Mounts the Workspace tool overlay into the container (currently [here](https://github.com/pwncollege/dojo/blob/master/dojo_plugin/api/v1/docker.py#L116)).
- Mounts the user's home directory into the container (currently [here](https://github.com/pwncollege/dojo/blob/master/dojo_plugin/api/v1/docker.py#L136)).

This is initialized with a [different dojo-init](https://github.com/pwncollege/dojo/blob/master/workspace/core/init.nix), which does the following:

- Makes sure that certain standard files are sufficiently initalized (e.g., the `hacker` user exists in `/etc/passwd`, `/bin/sh` is a file that makes sense, etc)
- Sets the `/flag`
- If it is present, runs `/challenge/.init`

Challenge containers are started with a [command](https://github.com/pwncollege/dojo/blob/master/dojo_plugin/api/v1/docker.py#L92) of `sleep 6`, so they will time out after 6 hours.

## DOJO workspace

The DOJO provides standard security tooling for users by mounting in a nix-based overlay into `/nix` of every challenge launched.
This overlay is built (e.g., the nix packages are installed) by the [workspace-builder](https://github.com/pwncollege/dojo/tree/master/workspace) container, defined in [docker-compose.yml](https://github.com/pwncollege/dojo/blob/master/docker-compose.yml#L33).
This will be done before the DOJO can start up, imposing a delay on the start of a fresh dojo.

To improve isolation between the challenges themselves and the user tools, the DOJO uses a fuse-based overlay to block default challenge access to the `/nix` tools.
This lives in the [workspace_fs](https://github.com/pwncollege/dojo/tree/master/workspacefs) container, also launched (automatically) via compose.

## DOJO Homes

The DOJO supports persistent home directories per user.
These home directories live in a btrfs volume that the dojo stores in `/dojo/homes/btrfs.img`, with each home being a subvolume.
These are mounted in `/dojo/homes` and mapped into each docker container.
You can inspect and manage these with, e.g., `btrfs subvolume list /data/homes`.

Each user gets 1gb of space (TODO: where is this defined??).

User home directories are mounted into the docker container through a clever use of docker volume plugins:

- The [homefs container](https://github.com/pwncollege/dojo/tree/master/homefs) starts a service that talks over a [unix socket called "homefs"](https://github.com/pwncollege/dojo/blob/master/homefs/Dockerfile#L18) in the [plugins directory](https://github.com/pwncollege/dojo/blob/master/docker-compose.yml#L76) of the docker-in-docker daemon.
- The home dir mount is [specified](https://github.com/pwncollege/dojo/blob/master/dojo_plugin/api/v1/docker.py#L136) with a type of `homefs`.
- This causes docker to automatically talk to the homefs service to mount the subvolume.

## DOJO Workspace Access

Access to the DOJO workspace happens one of two protocols.

### HTTP

HTTP access is [proxied through CTFd](https://github.com/pwncollege/dojo/blob/master/dojo_plugin/pages/workspace.py#L35).
Services are [automatically started](https://github.com/pwncollege/dojo/tree/master/workspace/services) in the user's container when the request is received by [dojo-plugin](https://github.com/pwncollege/dojo/blob/master/dojo_plugin/api/v1/workspace.py#L73).

### SSH

SSH is handled by the [sshd container](https://github.com/pwncollege/dojo/tree/master/sshd).
This container checks the public key provided against the keys table in the database, retrieves the right user, and `docker exec`s into that user's running container.

## dojofs

TODO: what is this?

## Multi-node

TODO

## DOJO Logs

You might want to look at some logs while administrating or developing the dojo.
The most useful logs are:

- **dojo-init:** `docker logs dojo` (e.g., logs of the outer docker)
- **dojo:** `journalctl -b -u pwn.college.*`
- **ctfd:** `docker logs ctfd`
- **nginx:** `docker logs nginx-proxy`

All of these except for the first one should be run inside the outer docker.
If you are outside of the outer docker (e.g., on the host itself), you can do stuff like `docker exec dojo journalctl -b -u dojo-up`.
