# DOJO

Deploy a pwn.college dojo instance!

## Details

The pwn.college dojo infrastructure is based on [CTFd](https://github.com/CTFd/CTFd).
CTFd provides for a concept of users, challenges, and users solving those challenges by submitting flags.
From there, this repository provides infrastructure which expands upon these capabilities.

The pwn.college infrastructure allows users the ability to "start" challenges, which spins up a private docker container for that user.
This docker container will have the associated challenge binary injected into the container as root-suid, as well as the flag to be submitted as readable only by the the root user.
Users may enter this container via `ssh`, by supplying a public ssh key in their profile settings, or via vscode in the browser ([code-server](https://github.com/cdr/code-server)).
The associated challenge binary may be either global, which means all users will get the same binary, or instanced, which means that different users will receive different variants of the same challenge.

## Setup

```sh
curl -fsSL https://get.docker.com | /bin/sh

DOJO_PATH="./dojo"
DATA_PATH="./dojo/data"

git clone https://github.com/pwncollege/dojo "$DOJO_PATH"
docker build -t pwncollege/dojo "$DOJO_PATH"

docker run \
    --name dojo \
    --privileged \
    -v "${DOJO_PATH}:/opt/pwn.college" \
    -v "${DATA_PATH}:/data:shared" \
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

### Local Setup

By default, the dojo will initialize itself to listen on and serve from `localhost.pwn.college` (which resolves 127.0.0.1).
This is fine for development, but to serve your dojo to the world, you will need to update this (see Production Setup).

It will take some time to initialize everything and build the challenge docker image.
You can check on your container (and the progress of the initial build) with:

```sh
docker exec dojo dojo logs
```

Once things are setup, you should be able to access the dojo and login with username `admin` and password `admin`.
You can change these admin credentials in the admin panel.

### Production Setup

Customizing the setup process is done through `-e KEY=value` arguments to the `docker run` command.
You can stop the already running dojo instance with `docker stop dojo`, and then re-run the `docker run` command with the appropriately modified flags.

In order to specify that the dojo should be running in a production environment, you can modify `DOJO_ENV`; for example: `-e DOJO_ENV=production`.
This will switch from the default development settings to production settings, which will, for example, disable the `flask` debugger.

In order to change where the host is serving from, you can modify `DOJO_HOST`; for example: `-e DOJO_HOST=example.com`.
In order for this to work correctly, you must correctly point the domain at the server's IP via DNS.

More of these configuration options (and defaults) can be found in [./dojo/dojo-init](./dojo/dojo-init) (and also modified in `dojo/config.env`).

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

Once logged in, you can add a dojo by visiting `/dojos/create`. Dojos are contained within git repositories.
Refer to [the example dojo](https://github.com/pwncollege/example-dojo) for more information.

## Cloud Backups

If configured properly, the dojo will store the hourly database backups into an S3 bucket of your choosing.

TODO ADD MORE HERE

## Contributing

We love Pull Requests! 🌟
Have a small update?
Send a PR so everyone can benefit.
For more substantial changes, open an issue to ensure we're on the same page.
Together, we make this project better for all! 🚀

You can run the dojo CI testcases locally using `test/local-tester.sh`.
