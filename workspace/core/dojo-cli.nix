{ pkgs }:

pkgs.writeScriptBin "dojo" ''
#!${pkgs.python3}/bin/python3

from urllib import request
import argparse
import json
import sys
import os

DOJO_URL = "http://pwn.college:80"
DOJO_API = f"{DOJO_URL}/pwncollege_api/v1"

def get_token() -> str | None:
    return os.environ.get("DOJO_AUTH_TOKEN")

def whoami() -> int:
    """
    Calls the WHOAMI integration api, printing information
    about the current user such as userID and username.
    """

    # Make request using dojo auth token.
    token = get_token()
    if not token:
        print("Failed to find authentication token (DOJO_AUTH_TOKEN). Did you change environment variables?")
        return 4
    
    httpRequest = request.Request(
        f"{DOJO_API}/integrations/whoami",
        method="GET",
        headers = {
            "auth_token": token
        },
    )
    response = request.urlopen(httpRequest, timeout=5.0)

    # Check for errors in response.
    try:
        response_json = json.loads(response.read().decode())
    except:
        print(f"WHOAMI request failed ({response.status}): malformed response from server")
        return 2
    if response.status != 200 or not response_json["success"]:
        print(f"WHOAMI request failed ({response.status}): {response_json["error"]}")
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
