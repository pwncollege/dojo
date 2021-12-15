# pwn.college

Deploy a pwn.college instance!

## Details

The pwn.college infrastructure is based on [CTFd](https://github.com/CTFd/CTFd).
CTFd provides for a concept of users, challenges, and users solving those challenges by submitting flags.
From there, this repository provides infrastructure which expands upon these capabilities.

The pwn.college infrastructure allows users the ability to "start" challenges, which spins up a private docker container for that user.
This docker container will have the associated challenge binary injected into the container as root-suid, as well as the flag to be submitted as readable only by the the root user.
Users may enter this container via `ssh`, by supplying a public ssh key in their profile settings, or via vscode in the browser ([code-server](https://github.com/cdr/code-server)).
The associated challenge binary may be either global, which means all users will get the same binary, or instanced, which means that different users will receive different variants of the same challenge.

## Setup

Clone the repository and init the submodules:
```sh
git clone https://github.com/pwncollege/dojo /opt/dojo
git -C /opt/dojo submodule update --init --recursive
```

Assuming you already have ssh running on port 22, you will want to change that so that users may ssh via port 22.

Change the line in `/etc/ssh/sshd_config` that says `Port 22` to `Port 2222`, and then restart ssh:
```sh
service ssh restart
```

The only dependency to run the infrastructure is docker, which can be installed with:
```sh
curl -fsSL https://get.docker.com | /bin/sh
```

Finally, run the infrastructure which will be hosted on domain <DOMAIN> with:
```sh
SETUP_HOSTNAME=<DOMAIN> ./run.sh
```

## Challenges

Place the challenges in `data/challenges`.
The structure is as follows:
- `data/challenges/modules.yml`
- `data/challenges/<CATEGORY>/_global/`
- `data/challenges/<CATEGORY>/<CHALLENGE>/`
- `data/challenges/<CATEGORY>/<CHALLENGE>/_global/`
- `data/challenges/<CATEGORY>/<CHALLENGE>/<i>/`

The `_global` directories contain "global" files that will always be inserted into the challenge instance container for a given category or challenge.

The `<i>` directories contain additional files which enable user-randomized challenges.

These files will end up in the challenge instance container in `/challenges`. Everything will be root-suid.

### modules.yml

This file specifies some module metadata.
The basic structure looks something like:
```
- name: Introduction
  permalink: introduction
  category: intro
  deadline: "2021-08-31 23:00:00"
  late: 0.5
  lectures:
        - name: "Introduction: What is Computer Systems Security"
          video: bJTThdqui0g
          playlist: PL-ymxv0nOtqrxUaIefx0qEC7_155oPEb7
          slides: 1YlTxeZg03P234EgG4E4JNGcit6LZovAxfYGL1YSLwfc
```
Only name and permalink are required; the other fields are optional.
