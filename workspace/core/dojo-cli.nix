{ pkgs }:

pkgs.writeScriptBin "dojo" ''
#!${pkgs.python3}/bin/python3

import requests
import argparse
import sys
import os

DOJO_URL = "http://pwn.college:80"
DOJO_API = f"{DOJO_URL}/pwncollege_api/v1"

def get_token():
    return os.environ.get("DOJO_AUTH_TOKEN")

def whoami() -> int:
    """
    Calls the WHOAMI integration api, printing information
    about the current user such as userID and username.
    """

    # Make request using dojo auth token.
    response = requests.get(
        f"{DOJO_API}/integrations/whoami",
        headers = {
            "auth_token": get_token()
        }
    )

    # Check for errors in response.
    try:
        response_json = response.json()
    except:
        print(f"WHOAMI request failed ({response.status_code}): malformed response from server")
        return 2
    if response.status_code != 200 or not response.json()["success"]:
        print(f"WHOAMI request failed ({response.status_code}): {response_json["error"]}")
        return 3

    # Print who's hacking.
    print(response_json["message"])
    return 0

def main():
    parser = argparse.ArgumentParser(
        prog="dojo",
        description="Command-line application for interacting with the dojo from inside of the challenge environment."
    )

    subparsers = parser.add_subparsers(
        dest="command",
        help="Dojo command to execute, not case sensitive."
    )

    whoami_parser = subparsers.add_parser(
        name="whoami",
        help="Prints information about the current user (you!)."
    )
    
    args = parser.parse_args()

    if args.command.lower() == "whoami":
        return whoami()
    else:
        parser.print_help()
        return 1

if __name__ == "__main__":
    sys.exit(main())

''