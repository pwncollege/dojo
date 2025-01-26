# Deployment

While we recommend using the [pwn.college](https://pwn.college) deployment, you can also run the DOJO locally.

```sh
curl -fsSL https://get.docker.com | /bin/sh

DOJO_PATH="./dojo"
DATA_PATH="./dojo/data"

git clone https://github.com/pwncollege/dojo "$DOJO_PATH"
docker build -t pwncollege/dojo "$DOJO_PATH"

# this is needed for the dojo's networking
modprobe br_netfilter

docker run \
    --name dojo \
    --privileged \
    -v "${DOJO_PATH}:/opt/pwn.college" \
    -v "${DATA_PATH}:/data" \
    -p 22:22 -p 80:80 -p 443:443 \
    -d \
    pwncollege/dojo
```

This will run the initial setup, including building the challenge docker image.

> **Warning**
> **(MacOS)**
>
> It's important to note that while the dojo is capable of operating on MacOS (either x86 or ARM), MacOS has inherent limitations when it comes to nested Linux mounts within a MacOS bind mount.
> This limitation specifically affects `data/docker`, which necessitates the use of OverlayFS mounts, preventing nested docker orchestration from functioning properly.
> In order to circumvent this issue, you must ensure that`data/docker` is not backed by a MacOS bind mount.
> This can be accomplished by replacing the bind mount with a docker volume for `data/docker`, which will use a native Linux mount:
> ```sh
> -v "dojo-data-docker:/data/docker"
> ```

By default, the dojo will initialize itself to listen on and serve from `localhost.pwn.college` (which resolves to 127.0.0.1).
This is fine for development, but to serve your dojo to the world, you will need to update this (see Production Deployment).

It will take some time to initialize everything and build the challenge docker image.
You can check on your container (and the progress of the initial build) with:

```sh
docker exec dojo dojo logs
```

Once things are setup, you should be able to access the dojo and login with username `admin` and password `admin`.
You can change these admin credentials in the admin panel.

## Production Deployment

Customizing the setup process is done through `-e KEY=VALUE` arguments to the `docker run` command, or by modifying the `$DATA_PATH/config.env` file.
You can stop the already running dojo instance with `docker stop dojo`, and then re-run the `docker run` command with the appropriately modified flags.

In order to specify that the dojo should be running in a production environment, you can modify `DOJO_ENV`; for example: `-e DOJO_ENV=production`.
This will switch from the default development settings to production settings, which will, for example, disable the `flask` debugger.

In order to change where the host is serving from, you can modify `DOJO_HOST`; for example: `-e DOJO_HOST=example.com`.
In order for this to work correctly, you must correctly point the domain at the server's IP via DNS.

More of these configuration options (and defaults) can be found in [./dojo/dojo-init](./dojo/dojo-init).

## Updating

When updating your dojo deployment, there is only one supported method in the `dojo` directory:

```sh
docker rm -f dojo
git -C "$DOJO_PATH" pull
docker build -t pwncollege/dojo "$DOJO_PATH"
docker run ... # (see Setup)
```

This will cause downtime when the dojo is rebuilding.

Some changes _can_ be applied without a complete restart, however _this is not guaranteed_.

If you really know what you're doing (the changes that you're pulling in are just to `ctfd`), inside the `dojo` container you can do the following:

```sh
dojo update
```

Note that `dojo update` is not guaranteed to be successful and should only be used if you fully understand each commit/change that you are updating.

## Customization

_All_ dojo data will be stored in the `./data` directory.

Once logged in, you can add a dojo by visiting `/dojos/create`.
Dojos are contained within git repositories.
Refer to [the example dojo](https://github.com/pwncollege/example-dojo) for more information.

If configured properly, the dojo will store the hourly database backups into an S3 bucket of your choosing.

## Multi-node Deployment

Setting up a multi-node deployment allows you to scale your dojo infrastructure across multiple nodes, with a central "main" node and additional "workspace" nodes.

### Build The Image

Refer to the standard deployment instructions above for how to build the dojo image and configure the host environment.

### Set Up The Main Node

Run the main node container, which will act as the central management point:

```sh
DOJO_PATH="./dojo"
DATA_PATH="/tmp/dojo-data-main"

docker run \
    --name dojo-main \
    --privileged \
    -v "${DOJO_PATH}:/opt/pwn.college" \
    -v "${DATA_PATH}:/data" \
    -p 22:22 -p 80:80 -p 443:443 -p 51820:51820/udp \
    -d \
    pwncollege/dojo
```

Pay particular attention to the `DATA_PATH`, which must be unique for each node if you are running multiple nodes on the same host.
Additionally, unlike the standard deployment, the main node must have port `51820/udp` exposed (for WireGuard) if you are going to be deploying workspace nodes across multiple hosts.

Retrieve configuration data from the main node:

```sh
docker exec -it dojo-main bash
dojo node show | grep -oP 'WORKSPACE_KEY: \K[A-Za-z0-9+/]+={0,2}'  # This is the WORKSPACE_KEY
ip -4 addr show eth0 | grep -oP 'inet \K[0-9\.]+'                  # This may be the DOJO_HOST
```

The `WORKSPACE_KEY` will be necessary to authenticate workspace nodes with the main node.
If you already have a `DOJO_HOST` (for example, a publicly accessible IP address), you can use that; otherwise, if you're running multiple nodes on the same host, this IP address (assigned by Docker) will be the `DOJO_HOST`.
The important detail is that the `DOJO_HOST` must be reachable by the workspace node.

### Set Up a Workspace Node

You may run a workspace node on the same host as the main node, or on a different host; all that matters is that the workspace node can reach the main node.
If you do decide to run the workspace node on a different host, make sure to refer to the standard deployment instructions above for how to build the dojo image and configure the host environment.

In order to run a workspace node container, use the `WORKSPACE_KEY` and `DOJO_HOST` obtained from the main node (and `WORKSPACE_NODE` id if you have multiple workspace nodes):

```sh
WORKSPACE_NODE=1    # The node id for this workspace node
WORKSPACE_KEY=...   # Replace with the WORKSPACE_KEY
DOJO_HOST=...       # Replace with the DOJO_HOST

DOJO_PATH="./dojo"
DATA_PATH="/tmp/dojo-data-workspace"

docker run \
    --name dojo-workspace \
    --privileged \
    -e DOJO_HOST=$DOJO_HOST \
    -e WORKSPACE_KEY=$WORKSPACE_KEY \
    -e WORKSPACE_NODE=$WORKSPACE_NODE \
    -v "${DOJO_PATH}:/opt/pwn.college" \
    -v "${DATA_PATH}:/data" \
    -d \
    pwncollege/dojo
```

Again, pay particular attention to the `DATA_PATH`, which must be unique for each node if you are running multiple nodes on the same host.
In this case `WORKSPACE_NODE=1` indicates that this is a workspace node (the main node is always, and by default, `WORKSPACE_NODE=0`).
If you want to add multiple workspace nodes, you must increment this id for each additional workspace node.
Each workspace node must have a unique `WORKSPACE_NODE` value, and the values must be contiguous, starting from 1.

Retrieve the `NODE_KEY` for the workspace node:

```sh
docker exec -it dojo-workspace bash
dojo node show | grep -oP 'public key: \K[A-Za-z0-9+/]+={0,2}'  # This is the NODE_KEY
```

This `NODE_KEY` is needed in order to add the workspace node to the main node.

At this point, you can also double-check that the workspace node can reach the main node:

```sh
docker exec -it dojo-workspace bash
ping $DOJO_HOST
```

If this fails, you may need to review and adjust your network configuration.

### Add The Workspace Node To The Main Node

On the main node, add the workspace node using its `NODE_KEY` (and `WORKSPACE_NODE` id if you have multiple workspace nodes):

```sh
docker exec -it dojo-main bash
NODE_ID=1     # Replace with the node id
NODE_KEY=...  # The NODE_KEY for the workspace node
dojo node add $NODE_ID $NODE_KEY
dojo compose restart --no-deps ctfd
```

After a short delay, you should be able to reach the workspace node from the main node:

```sh
docker exec -it dojo-main bash
NODE_ID=1     # Replace with the node id
ping 192.168.42.$(($NODE_ID + 1))
```

## Common DOJO Errors

### Non-readable build context

```
ERROR: failed to solve: error from sender: open docker: permission denied
```

Some directory in your git repo is not readable.
This can happen if you've used `$PWD/data` as your data volume (this is okay --- `data` is in the `.dockerignore`, so it is not accessed when building) and then moved your `data` dir to, e.g., `data.bak` (which would no longer match the `.dockerignore`, causing the docker daemon to try, and fail, to access it).


### Shared mount woes

In the docker-compose logs:

```
Error response from daemon: path /run/homefs is mounted on /run/homefs but it is not a shared mount
```

- Make sure your `/data` directory is a shared mount.
  If you are mounting it into the outer docker via `-v`, do:

  `-v /host/path:/data:shared`

- If problem persists: rebuild the outer docker container
