# Challenge

A challenge is defined by a docker image which follows the *capture the flag* paradigm.
Both the in-environment infrastructure (e.g., VSCode, desktop environment, virtual machines, etc) and standard tools (e.g., gdb, ghidra, pwntools, wireshark, etc) are made available to *all* challenge images with [nix](https://nixos.org) via a read-only mount at `/nix`, which contains all of the necessary programs, libraries, and configuration files.
This means that the challenge image need not concern itself with the specifics of the environment in which it will run, and can instead focus on the challenge itself.

## Challenge Entrypoint

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

## Challenge Bashrc

`/challenge/.bashrc`

> **Deprecated**
>
> This interface was created before the DOJO was able to run arbitrary docker images as challenges.
> We will probably remove this interface in the future in favor of `/etc/bashrc` or `/run/challenge/etc/bashrc` (we want to make sure both the DOJO and the challenge each have some control over the bashrc).
> If you have thoughts or concerns on this, please open an issue!

## $PATH's /run/challenge/bin

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

## DOJO Workspace Requirements

There is no perfect way to marry together a file system that meets the precise needs of the DOJO, the challenge, and the user; nevertheless, we try our best.

DOJO completely owns the following directories:
- `/run/workspace`
- `/run/dojo`
- `/run/current-system`
- `/nix`

The user completely owns the following directories:
- `/home/hacker`

The challenge owns everything else subject to the following constraints/understanding:
- DOJO will ensure `/tmp` exists, with permisisons `root:root 01777`.
- DOJO will control `/etc/passwd` and `/etc/group` for the `hacker` (UID 1000) and `root` (UID 0) users, with permissions `root:root 0644`.
- `/bin/sh` must be POSIX compliant; DOJO will symlink `/bin/sh` to `/run/dojo/bin/sh` if it does not exist.
- `/usr/bin/env` must be POSIX compliant; DOJO will symlink `/usr/bin/env` to `/run/dojo/bin/env` if it does not exist.
- Various configuration files may be automatically utilized by the DOJO; for example, `/run/dojo/bin/bash`, the user's default shell, will try to to use `/etc/bashrc`[^1], `/etc/inputrc`, and `/etc/nsswitch.conf`.

[^1]: This is *different* than `ubuntu:24.04`'s use of `/etc/bash.basrch`
