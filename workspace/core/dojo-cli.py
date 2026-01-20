import argparse
import os
import sys
import requests

DOJO_API = "http://pwn.college:80/pwncollege_api/v1"
DOJO_AUTH_TOKEN = os.environ.get("DOJO_AUTH_TOKEN")


def whoami():
    response = requests.get(
        f"{DOJO_API}/users/me",
        headers={"Authorization": f"Bearer {DOJO_AUTH_TOKEN}"},
        timeout=5.0,
    )
    data = response.json()
    if not response.ok:
        sys.exit(data.get("error", "Unknown error"))
    print(f"You are the epic hacker {data['name']} ({data['id']}).")


def main():
    parser = argparse.ArgumentParser(
        prog="dojo",
        description="Command-line application for interacting with the dojo from inside of the challenge environment.",
    )
    subparsers = parser.add_subparsers(dest="command", help="Dojo command to execute, not case sensitive.")
    subparsers.add_parser(name="whoami", help="Prints information about the current user (you!).")
    args = parser.parse_args()
    if not DOJO_AUTH_TOKEN:
        sys.exit("Missing DOJO_AUTH_TOKEN.")
    if args.command and args.command.lower() == "whoami":
        return whoami()
    parser.print_help()
    sys.exit(1)


if __name__ == "__main__":
    main()
