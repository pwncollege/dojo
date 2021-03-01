# pwn.college

This repository has the artifacts necessary for deploying a pwn.college instance.

## Setup

The following has been tested on a fresh ubuntu:20.04 machine.
This setup process assumes that the pwn.college DNS has been setup already.
Remember to open ports 22, 80, and 443.

```bash
sudo su
cd /opt
git clone https://github.com/pwncollege/pwncollege
cd pwncollege
./setup.sh <INSTANCE>
./run.sh
```

From here, you must go to `https://<INSTANCE>.pwn.college/`, and quickly setup the CTFd instance.
You can create a new docker challenge and user flag from the admin interface.
It is expected that challenges will exist at `/opt/pwncollege/.data/challenges/<USER_ID>/<CATEGORY>/<NAME>`.
You can also use `global` as the `<USER_ID>` if you don't want per-user challenges.
