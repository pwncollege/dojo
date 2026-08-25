# Deployment

While we recommend using the [pwn.college](https://pwn.college) deployment, you can also run the DOJO on an x86-64 Linux host with Docker and Nix installed. Nix must have flakes enabled, and the host must permit privileged containers.

For a local development instance, the deployment helper builds the NixOS outer image, imports it into Docker, starts it, and publishes the web and SSH ports:

```sh
./deploy.sh -b -p
```

The web interface will be available at `http://localhost.pwn.college`, and SSH will be published on port `2222`.

## Build and Run

Use a persistent host directory for production data:

```sh
DOJO_PATH="$PWD/dojo"
DATA_PATH="$PWD/dojo-data"

git clone https://github.com/pwncollege/dojo "$DOJO_PATH"
mkdir -p "$DATA_PATH"
cd "$DOJO_PATH"

nix build .#dojo-image
docker import \
    --change 'CMD ["/init"]' \
    --change 'ENV LC_CTYPE=C.UTF-8' \
    --change 'ENV PATH=/run/wrappers/bin:/run/current-system/sw/bin' \
    --change 'EXPOSE 22 80 443 8001' \
    --change 'STOPSIGNAL SIGRTMIN+3' \
    --change 'WORKDIR /opt/pwn.college' \
    result/tarball/nixos-system-*.tar.xz \
    pwncollege/dojo

sudo modprobe br_netfilter

docker run \
    --name dojo \
    --privileged \
    -v "${DOJO_PATH}:/opt/pwn.college" \
    -v "${DATA_PATH}:/data:shared" \
    -p 22:22 -p 80:80 -p 443:443 \
    -d \
    pwncollege/dojo

docker exec dojo dojo wait
```

The `.#dojo-image` flake output produces one NixOS root filesystem archive at `result/tarball/nixos-system-*.tar.xz`. Importing it with `CMD ["/init"]` starts systemd as PID 1. The outer container must remain privileged because it runs the Docker daemon and mount services used by learner workspaces.

The first startup can take some time while the workspace environment and challenge images are prepared. Inspect progress and failures through the native services:

```sh
docker exec dojo systemctl status dojo.target
docker exec dojo systemctl --failed
docker exec dojo journalctl -b -u dojo-ctfd
```

Once `dojo wait` succeeds, log in with username `admin` and password `admin`, then change those credentials in the admin panel.

The deployment target is Linux. Docker Desktop bind mounts do not reliably support the nested mounts required by `/data/docker`; if Docker Desktop is used for development, back that path with a Docker-managed volume rather than a host bind mount.

## Production Configuration

Pass configuration through `-e KEY=VALUE` arguments to `docker run`, or edit `$DATA_PATH/config.env`. Stop and recreate the outer container after changing environment arguments.

Set `DOJO_ENV=production` for production behavior:

```sh
-e DOJO_ENV=production
```

Set `DOJO_HOST` to the public hostname and point its DNS record at the server:

```sh
-e DOJO_HOST=example.com
```

Workspace traffic uses `workspace.$DOJO_HOST` by default. Override it when needed:

```sh
-e WORKSPACE_HOST=workspace.example.com
```

Configuration defaults and allowed environment names are defined by [`dojo/dojo-config`](../dojo/dojo-config). The NixOS modules under [`nix/`](../nix) expose those values to the native services.

Set `ENABLE_SPLUNK=true` to enable the native Splunk service and journal forwarding. On first start, the appliance downloads the official Splunk Enterprise 9.1.2 archive into `/data/splunk/cache`, verifies its checksum, and accepts the Splunk license during unattended initialization. An offline deployment must seed that archive in the cache before startup.

## Updating

Rebuild and import the image after updating the checkout, then recreate the outer container with the same data mount and environment:

```sh
git -C "$DOJO_PATH" pull
cd "$DOJO_PATH"
nix build .#dojo-image
docker import \
    --change 'CMD ["/init"]' \
    --change 'ENV LC_CTYPE=C.UTF-8' \
    --change 'ENV PATH=/run/wrappers/bin:/run/current-system/sw/bin' \
    --change 'EXPOSE 22 80 443 8001' \
    --change 'STOPSIGNAL SIGRTMIN+3' \
    --change 'WORKDIR /opt/pwn.college' \
    result/tarball/nixos-system-*.tar.xz \
    pwncollege/dojo
docker rm -f dojo
docker run ...
docker exec dojo dojo wait
```

Recreating the outer container does not remove data stored under `$DATA_PATH`, but the service is unavailable during replacement.

## Customization

All persistent DOJO state lives under `/data` in the outer container. Keep that path on durable storage and include it in backups.

Once logged in, add a dojo at `/dojos/create`. Dojos are contained in Git repositories; see the [example dojo](https://github.com/pwncollege/example-dojo) for a starting point.

The hourly backup service creates local database dumps. When `BACKUP_AES_KEY_FILE` and `S3_BACKUP_BUCKET` are configured, the daily cloud-backup service encrypts recent dumps and uploads them to S3.

## Multi-node Deployment

A multi-node deployment has one main node and one or more workspace nodes. Every outer container uses the same NixOS image, runs privileged, and needs distinct `/data` and `/data/docker` storage.

The `-M` option creates a three-container development cluster on one host:

```sh
./deploy.sh -b -M -p
```

For a deployment across hosts, point both the dojo and workspace hostnames at the main node. Start it with a shared workspace secret and publish WireGuard in addition to the public web and SSH services:

```sh
DOJO_HOST="example.com"
WORKSPACE_HOST="workspace.example.com"
WORKSPACE_SECRET="$(openssl rand -hex 16)"

docker run \
    --name dojo-main \
    --privileged \
    -e WORKSPACE_NODE=0 \
    -e "DOJO_HOST=$DOJO_HOST" \
    -e "WORKSPACE_HOST=$WORKSPACE_HOST" \
    -e "WORKSPACE_SECRET=$WORKSPACE_SECRET" \
    -v "${DOJO_PATH}:/opt/pwn.college" \
    -v "${DATA_PATH}-main:/data:shared" \
    -p 22:22 -p 80:80 -p 443:443 \
    -p 51820:51820/udp \
    -d \
    pwncollege/dojo

docker exec dojo-main dojo wait
docker exec dojo-main dojo-node refresh
WORKSPACE_KEY="$(docker exec dojo-main cat /data/wireguard/publickey)"
```

Start each workspace node with a contiguous numeric ID beginning at 1. `DOJO_HOST` identifies the main node's reachable WireGuard endpoint, `WORKSPACE_HOST` remains the main node's public learner URL, and storage uses the main node's private WireGuard address.

```sh
WORKSPACE_NODE=1
STORAGE_HOST="192.168.42.1"

docker run \
    --name "dojo-node${WORKSPACE_NODE}" \
    --privileged \
    -e "WORKSPACE_NODE=$WORKSPACE_NODE" \
    -e "WORKSPACE_KEY=$WORKSPACE_KEY" \
    -e "WORKSPACE_SECRET=$WORKSPACE_SECRET" \
    -e "DOJO_HOST=$DOJO_HOST" \
    -e "STORAGE_HOST=$STORAGE_HOST" \
    -e "WORKSPACE_HOST=$WORKSPACE_HOST" \
    -v "${DOJO_PATH}:/opt/pwn.college" \
    -v "${DATA_PATH}-node${WORKSPACE_NODE}:/data:shared" \
    -d \
    pwncollege/dojo

docker exec "dojo-node${WORKSPACE_NODE}" dojo wait
docker exec "dojo-node${WORKSPACE_NODE}" dojo-node refresh
NODE_KEY="$(docker exec "dojo-node${WORKSPACE_NODE}" cat /data/wireguard/publickey)"
```

Register the workspace node on the main node:

```sh
docker exec dojo-main dojo-node add "$WORKSPACE_NODE" "$NODE_KEY"
```

`dojo-node add` and `dojo-node del` apply the WireGuard topology, restart services that cache the node list, and wait for readiness. Workspace nodes do not publish ports 80, 443, or 4201. The main proxy forwards workspace HTTP and WebSocket traffic to each worker's private port 8888 over WireGuard, so per-node DNS names and public worker endpoints are unnecessary.

## Shared Mount Errors

The `/data` bind mount must use shared propagation. If a mount service reports that a path is not shared, recreate the container with:

```sh
-v /host/path:/data:shared
```

If the error remains, verify the host mount propagation and inspect the relevant unit with `journalctl` inside the outer container.
