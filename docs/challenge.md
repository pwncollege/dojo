# Challenge

A **challenge** is an interactive, educational task explicitly designed for students. Successfully completing a challenge demonstrates that a student has acquired or validated the intended knowledge or skill.

## Core Properties

Challenges have two fundamental properties:

- **Binary Outcome**: Each challenge has exactly two states—*solved* or *unsolved*. Crucially, there is no concept of "failing" a challenge. Challenges begin as unsolved, and once solved, remain permanently solved.
- **Independent Completion**: Each student works independently on challenges. One student's success does not impact another student's ability to attempt or solve the same challenge.

## Verification Inspired by Capture The Flag Competitions

Challenges utilize a verification method inspired by "Capture The Flag" (CTF) competitions:

- Students clearly recognize when they have solved a challenge by acquiring a unique "flag," a student-specific piece of text formatted according to a predefined standard. Successfully obtaining this flag indicates completion.

## Technical Implementation&#x20;

On the dojo, challenges are concretely implemented as follows:

Students may start (or restart) a dedicated instance of a challenge at any time. Each instance is an isolated Linux environment using standard Linux access controls to secure the "flag":

- The flag is a simple text file located at `/flag`, readable only by user-id-0 (`root`).
- Students operate as user-id-1000 (`hacker`) and therefore cannot directly read the flag.
- The challenge environment provides specially designated program(s) running as user-id-0.

Typically, these programs utilize the Linux permission `setuid`:

- Normally, programs execute with the privileges of the user that starts them.
- A program marked `setuid` instead executes with the privileges of the user who owns it.
- Consequently, a `setuid` program owned by user-id-0 runs with root privileges, even if initiated by user-id-1000.

Alternatively, a challenge might start long-running processes as user-id-0 during challenge initialization.

The critical factor is that a user-id-0 program can access the flag. Students must interact with this privileged program in challenge-specific ways—determined by the program’s behavior and logic—to "capture" the flag and thus solve the challenge. The simplicity of this structure—just a Linux environment with two users (one privileged, one not) and a text file—allows for diverse, complex challenges.

## Requirements for Challenge Authors

To conform with this definition, a challenge author only needs to provide a filesystem, which could be, for example:

- A single, statically linked binary marked `setuid` and owned by root.
- A more intricate setup built on a standard Ubuntu filesystem, including dependencies such as `python`, `firefox`, and `qemu-system`, coordinated by a custom `setuid` binary.

Authors can also specify an optional initialization command that will be executed as user-id-0 during challenge initialization.

Specifically, this information is provided in the form of a [`docker` image](https://docs.docker.com/get-started/docker-concepts/the-basics/what-is-an-image/), which may optionally specify a [`CMD`](https://docs.docker.com/reference/dockerfile/#cmd) to be run during initialization. Note that the `ENTRYPOINT` of the image is ignored.

## Challenge Initialization

The dojo handles all additional setup automatically:

- Creation of the `/flag` file with the correct, student-specific secret content, accessible only by root.
- Execution of any specified initialization commands as user-id-0.
- Provision of the challenge environment for the student as user-id-1000.







# Challenge

A **challenge** is an interactive, educational task explicitly designed for students.
Completing a challenge successfully indicates that the student has acquired or demonstrated the targeted knowledge or skill.

A challenge is defined by two core properties:
- **Binary Outcome**: Each challenge has exactly two states—solved or unsolved. Importantly, there is no concept of "failing" a challenge; instead, a challenge begins in an unsolved state and, once solved, remains permanently solved.
- **Independent Completion**: Students tackle challenges independently. One student's completion of a challenge does not affect another student's opportunity or ability to attempt and solve that same challenge.

To support these properties, challenges utilize:
- **Flag-Based Verification**: Students explicitly know when they have solved a challenge by obtaining a unique "flag"—a distinct, student-specific piece of text formatted according to a known standard. Acquiring this flag can only be achieved through correctly solving the challenge.

Let's be a little more specific and technical on how this is implemented on the dojo.

At any point, a student can start (or restart) a dedicated instance of a challenge.
This instance is an isolated Linux environment, that uses standard Linux access-control to implement the "flag".
The flag is a simple text file (located at `/flag`), and is only readable by user-id-0 (`root`).
The student runs as user-id-1000 (`hacker`), and so they cannot simply read the flag.
Instead, the challenge has some program(s) that run as user-id-0.

Typically this is achieved by marking those challenge program(s) `setuid`, which is a special Linux permission.
Normally when a user runs a program, that program runs with the same privileges as the user that started the program.
However, a program which is marked `setuid` will instead run as the user that *owns* the program.
And so, a program owned by user-id-0 which is marked `setuid` will run with the privileges of user-id-0, even if it was started by user-id-1000.

Alternatively, as part of its initialization, a challenge might just start up some long-running programs as user-id-0.

What matters is that a program running as user-id-0 can read the flag, and that only by interacting with this program in some challenge-specific way, as determined by the behavior and implementation of this program, can a student "capture" the flag, and therefore *solve* the challenge.

Notice just how simple this challenge-definition is: a Linux environment with two users--one privileged, one not--and a text file.
That's it.
Everything else is just derived from very-standard Linux mechanisms.
And yet from this simplicity, we can create challenges that explore all sorts of complex and interesting topics, ensuring that the flag is protected until it has been earned.

In order to comform with this definition, all that a challenge author must provide is a filesystem.
This filesystem could be as simple as a single statically linked binary owned by root and marked `setuid`.
It could be more complicated, using a standard ubuntu filesystem as its base, with `python`, `firefox`, and `qemu-system` installed into it to provide some interesting dependencies that some custom-written program marked `setuid` orchestrates.

A challenge author may additionally specify an initialization command that should be run as user-id-0 at the start of creating a challenge instance.

The dojo takes care of the rest:
- The `/flag` is created, its contents set to the "correct" student-specific secret value, and its permissions set to be readable only by root.
- The (optional) initialization command is run as user-id-0.
- The student begins in the environment as user-id-1000.


## Creating a New Challenge

Creating a new challenge involves two key considerations:
1. **Technical Implementation**: This includes all practical steps required to integrate a new challenge into the dojo environment, ensuring it is visible, accessible, functional, and solvable by students.
2. **Educational Philosophy**: This addresses the design of a challenge, ensuring it aligns with the intended audience's skill level and effectively balances complexity with clearly defined learning outcomes.

## What Exactly is a Challenge?

Before proceeding further, it's important to clarify what we mean by a "challenge" in the context of the dojo.

A challenge is an interactive, educational task designed specifically for students to solve. Successful completion typically indicates that the student has acquired or demonstrated the intended knowledge or skill.

At a high-level, a challenge has these essential elements:
- **Binary Outcome**: Each challenge has a clear, binary outcome—it is either solved or unsolved, with no intermediate state. Importantly, a challenge does not have a "failure" state; it starts unsolved and may eventually become solved. Once solved, the status is permanent.
- **Flag-Based Verification**: Students clearly know when they have solved a challenge, typically by acquiring a "flag"--a unique piece of text following a specific known format that can only be obtained by successfully solving the challenge.
- **Independent Completion**: Students work on challenges independently. One student's completion of a challenge does not influence or impact another student's ability to attempt or solve that same challenge.

Let's be a little more specific and technical on how


## Deploying a New Challenge



---

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

During initialization, the nix profile at `/nix/var/nix/profiles/dojo-workspace` is symlinked into `/run/dojo`.
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
