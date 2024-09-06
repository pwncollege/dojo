# DOJO

The pwn.college DOJO.

The best way to understand the DOJO is to experience it.
Try it out at [pwn.college](https://pwn.college).

## Background

In the Fall of 2018, tasked with the responsibility of teaching *Computer Systems Security* to a little over a hundred fourth-year undergraduate students at [Arizona State University](https://www.asu.edu), we were faced with a challenge: how do we best teach hundreds of students to become skilled *hackers* in just a single semester?
With a background in Capture The Flag (CTF) competitions, as members of [Shellphish](https://shellphish.net) and the DEF CON CTF organizing team [Order of the Overflow](https://www.oooverflow.io), we realized our best chance was to teach the course in the same way we learned: by doing.
And so, the night before the first lecture, at a coffee shop in Tempe, Arizona---late into the night---we bought the domain [pwn.college](https://pwn.college), created the first assignment, and glued together a simple netcat interface in what would become [the first version]((https://github.com/pwncollege/oldschool)) of the pwn.college DOJO.

For a more academic discussion of pwn.college, see our SIGCSE 2024 papers:
- [DOJO: Applied Cybersecurity Education In The Browser](https://sefcom.asu.edu/publications/dojo-sigcse24.pdf)
- [PWN The Learning Curve: Education-First CTF Challenges](https://sefcom.asu.edu/publications/pwn-sigcse24.pdf)

See also Connor's PhD work, which focuses on pwn.college:
- [Connor's PhD Dissertation](https://connornelson.com/docs/dissertation-hacking-the-learning-curve.pdf)
- [Connor's PhD Defense - 2024.02.15](https://www.youtube.com/watch?v=qjOBDE_atIk)
- [Connor's PhD Proposal - 2023.11.21](https://www.youtube.com/watch?v=e6JpB2o7QZ0)

And some ASU news articles:
- [New ASU institute to create national cybersecurity hub - 2024.06.26](https://news.asu.edu/20240628-science-and-technology-new-asu-institute-create-national-cybersecurity-hub)
- [The next generation of cybersecurity pros drill in the dojo - 2024.03.19](https://news.asu.edu/20240319-science-and-technology-next-generation-cybersecurity-pros-drill-dojo)
- [ASU's cybersecurity dojo - 2021.02.15](https://news.asu.edu/20210215-asu-cybersecurity-dojo-pwn-college-thwart-cyberattacks)


## High Level Technical Overview

The pwn.college DOJO infrastructure enables students to learn cybersecurity concepts through hands-on exercises, entirely within the browser.
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

### Creating a Challenge

A challenge is defined by a docker image which follows the *capture the flag* paradigm.
Both the in-environment infrastructure (e.g., VSCode, desktop environment, virtual machines, etc) and standard tools (e.g., gdb, ghidra, pwntools, wireshark, etc) are made available to *all* challenge images with [nix](https://nixos.org) via a read-only mount at `/nix`, which contains all of the necessary programs, libraries, and configuration files.
This means that the challenge image need not concern itself with the specifics of the environment in which it will run, and can instead focus on the challenge itself.

#### Challenge Entrypoint

`/challenge/.init`

Near the end of initialization, but before the workspace is accessible to the student, `/challenge/.init` is executed.
This program is run as the `root` user, and is responsible for setting up any dynamic challenge-specific configuration, or for starting any services that the challenge might require.
This program must exit (with a status code of `0`) before the workspace is made available to the student, and so it should fork off any long-running processes, and terminal quickly itself in order to make the workspace available as soon as possible.

> **Deprecated**
>
> This interface was created before the DOJO was able to run arbitrary docker images as challenges.
> Currently, the challenge image's `ENTRYPOINT` and `CMD` are entirely ignored.
> We plan to change this in the future; `ENTRYPOINT` will continue to be controlled by the DOJO, but `CMD` will be respected over `/challenge/.init`.
> If you want your challenge to be compatible with this future change, you should set the `CMD` of your challenge image to `/challenge/.init`.

#### Challenge Bashrc

`/challenge/.bashrc`

> **Deprecated**
>
> This interface was created before the DOJO was able to run arbitrary docker images as challenges.
> We will probably remove this interface in the future in favor of `/etc/bashrc` or `/run/challenge/etc/bashrc` (we want to make sure both the DOJO and the challenge each have some control over the bashrc).
> If you have thoughts or concerns on this, please open an issue!

#### $PATH's /run/challenge/bin

`/run/challenge/bin`

During initialization, the default nix profile at `/nix/var/nix/profiles/default` is symlinked into `/run/dojo`.
In order to make sure that these standard tools are easily accessible, `PATH` is set to prioritize `/run/dojo/bin` over the default `PATH`.
This means that when a user runs `gdb`, they will get the standard `gdb` provided by the workspace at `/run/dojo/bin/gdb`, instead of any other `gdb` that might be made available by the challenge image (e.g. `/usr/bin/gdb`).
The workspace provides for *many* tools in this way in order to provide a consistent environment for all challenges, ensuring that students are able to use the tools they are familiar with.

If a challenge wants to instead prioritize its own program(s), this can be done through symlinks in the `/run/challenge/bin` directory.
This should be done *sparingly*, and only when the challenge really expects a specific challenge-version of a program to be used by default.
Unfortunately some of the infrastructure programs might rely on the `PATH` to find their dependencies, and so doing this can sometimes break things (please open an issue if you find this to be the case).
However, if for example, you want to make sure that your challenge image's `python` (with specific challenge python-dependencies) is used when a student runs `python`, you can symlink `/run/challenge/bin/python` to the desired version of the program.

In other words, `PATH="/run/challenge/bin:/run/dojo/bin:$PATH"`.

By default, if there is no `/run/challenge/bin` directory, it is automatically symlinked from `/challenge/bin`.
This means that you can alternatively place your symlinks in `/challenge/bin` if you prefer; however, the `/challenge` interface is deprecated, and so long-term you should prefer `/run/challenge/bin`.

For more information about how `PATH` works, see [8.3 Other Environment Variables](https://pubs.opengroup.org/onlinepubs/9699919799/basedefs/V1_chap08.html#tag_08_03).

#### DOJO Workspace Requirements

There is no perfect way to marry together a file system that meets the precise needs of the DOJO, the challenge, and the user; however, perfect is the enemy of good.

DOJO owns the following directories:
- `/run/workspace`
- `/run/dojo`
- `/run/current-system`
- `/nix`

The user owns the following directories:
- `/home/hacker`

The challenge owns everything else subject to the following constraints/understanding:
- DOJO will ensure `/tmp` exists, with permisisons `root:root 01777`.
- DOJO will control `/etc/passwd` and `/etc/group` for the `hacker` (UID 1000) and `root` (UID 0) users, with permissions `root:root 0644`.
- `/bin/sh` must be POSIX compliant; DOJO will symlink `/bin/sh` to `/run/dojo/bin/sh` if it does not exist.
- `/usr/bin/env` must be POSIX compliant; DOJO will symlink `/usr/bin/env` to `/run/dojo/bin/env` if it does not exist.
- Various configuration files may be automatically utilized by the DOJO; please open an issue if you run into issues with this.

## Local Deployment

While we recommend using the [pwn.college](https://pwn.college) deployment, you can also run the DOJO locally.

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

### Production Deployment

Customizing the setup process is done through `-e KEY=VALUE` arguments to the `docker run` command, or by modifying the `$DATA_PATH/config.env` file.
You can stop the already running dojo instance with `docker stop dojo`, and then re-run the `docker run` command with the appropriately modified flags.

In order to specify that the dojo should be running in a production environment, you can modify `DOJO_ENV`; for example: `-e DOJO_ENV=production`.
This will switch from the default development settings to production settings, which will, for example, disable the `flask` debugger.

In order to change where the host is serving from, you can modify `DOJO_HOST`; for example: `-e DOJO_HOST=example.com`.
In order for this to work correctly, you must correctly point the domain at the server's IP via DNS.

More of these configuration options (and defaults) can be found in [./dojo/dojo-init](./dojo/dojo-init).

### Updating

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

### Customization

_All_ dojo data will be stored in the `./data` directory.

Once logged in, you can add a dojo by visiting `/dojos/create`. Dojos are contained within git repositories.
Refer to [the example dojo](https://github.com/pwncollege/example-dojo) for more information.

If configured properly, the dojo will store the hourly database backups into an S3 bucket of your choosing.

## Contributing

We love Pull Requests! 🌟
Have a small update?
Send a PR so everyone can benefit.
For more substantial changes, open an issue to ensure we're on the same page.
Together, we make this project better for all! 🚀

You can run the dojo CI testcases locally using `test/local-tester.sh`.
