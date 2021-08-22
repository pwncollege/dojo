# pwn.college

Deploy a pwn.college instance!

## Setup

```sh
curl -fsSL https://get.docker.com | /bin/sh
SETUP_HOSTNAME=<DOMAIN> ./run.sh
```

### Challenges

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

#### modules.yml

This file specifies some module metadata.
The basic structure looks something like:
```
- name: Example module
  permalink: example
  category: example
```
