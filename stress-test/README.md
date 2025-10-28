# pwn.college stress test — `pwn_users.json` generator

A small, local stress test tool that generates synthetic user activity for pwn.college-style modules.
It produces a JSON file (`pwn_users.json`) containing fake users, their usernames, total solves, and per-module solves. Use it to populate local dev fixtures, load-test dashboards, or exercise data pipelines without hitting any external services.

> This tool only generates local data and makes no network requests. Do not use it to impersonate or spam real services.

---

## Features

* Deterministic output via `seed` for reproducible tests.
* Configurable target user count, with safe minimum and maximum limits.
* Realistic-ish usernames with leetspeak and suffix variations.
* Per-user list of modules solved with per-module solve counts.
* Output in human-friendly JSON for easy consumption.

---

## Files

* `stress_test.py` — Python script that generates the JSON (this is the script you provided).
* `pwn_users.json` — generated output file (created after running the script).
* `README.md` — this file.

---

## Requirements

* Python 3.8 or newer. The script uses only Python standard library modules.

---

## Quick start

Run the generator from the repository root:

```bash
python3 stress_test.py
```

By default the script writes `pwn_users.json` into the current working directory and prints:

```
wrote <N> users to pwn_users.json
```

To inspect the file:

```bash
jq '.' pwn_users.json | less
# or, with Python
python3 -c "import json,sys; print(len(json.load(open('pwn_users.json'))))"
```

---

## Configuration

The script contains a few top-level variables you can tweak:

* `COUNT` — target number of users to generate. The script enforces:

  * minimum: 10
  * maximum: 15000
* `seed` — PRNG seed for reproducible results.
* `modules_pool` — list of module names used to sample per-user solves.

If you want command-line control, add a simple `argparse` wrapper. Example snippet:

```py
import argparse

parser = argparse.ArgumentParser()
parser.add_argument("--count", type=int, default=10000)
parser.add_argument("--seed", type=int, default=12345)
args = parser.parse_args()
# then use args.count and args.seed in the script
```

---

## Output format

Each element in the JSON array is an object like:

```json
{
  "Hacker UserName": "dark_cipher99",
  "Number of Solves": 17,
  "Modules Solved": [
    { "module": "Reverse Engineering", "solves": 3 },
    { "module": "Fuzz Dojo", "solves": 7 },
    { "module": "Pwntools Tutorials", "solves": 7 }
  ]
}
```

The full file is a JSON array of these objects.

---
