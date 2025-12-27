{ pkgs }:

pkgs.writeScriptBin "dojo" ''
#!${pkgs.python3}/bin/python3

from typing import Any
import urllib.request
import urllib.parse
import urllib.error
import argparse
import json
import sys
import os

DOJO_URL = "http://pwn.college:80"
DOJO_API = f"{DOJO_URL}/pwncollege_api/v1"

INCORRECT_USAGE = 1
TOKEN_NOT_FOUND = 2
API_ERROR = 3
INCORRECT = 4
START_FAILED = 5

def get_token() -> str | None:
    return os.environ.get("DOJO_AUTH_TOKEN")

def apiRequest(endpoint: str, method: str = "GET", args: dict[str, Any] = {}) -> tuple[int, str | None, dict[str, str]]:
    """
    Make a request to the given integration endpoint.
    Will call `sys.exit` if the auth token is not specified in the environment.

    Returns the http response code, an error message (or `None`), and a dictionary with the json response data.

    Supports `GET` and `POST` methods.
    """
    # Container authentication token required.
    token = get_token()
    if not token:
        print("Failed to find authentication token (DOJO_AUTH_TOKEN). Did you change environment variables?")
        sys.exit(TOKEN_NOT_FOUND)

    # Append args to URL.
    url = f"{DOJO_API}{endpoint}"
    if (len(args) > 0 and method == "GET"):
        url += f"?{urllib.parse.urlencode(args)}"

    # Construct HTTP request.
    match method:
        case "GET":
            request = urllib.request.Request(
                url,
                method="GET",
                headers={
                    "AuthToken":token
                }
            )
        case "POST":
            data = json.dumps(args).encode()
            request = urllib.request.Request(
                url,
                method="POST",
                data=data,
                headers={
                    "AuthToken":token,
                    "Content-Type": "application/json; charset=utf-8",
                }
            )
        case _:
            return 0, f"Unsupported method \"{method}\".", {}

    # Make request, handle errors.
    response_code = -1
    try:
        # Normal response.
        response = urllib.request.urlopen(request, timeout=5.0)
        response_code = response.status
        response_json = json.loads(response.read().decode())
        return response_code, None, response_json

    except urllib.error.HTTPError as error_response:
        # Error response (ie, 400), should still be OK.
        response_json = json.loads(error_response.read().decode())
        return error_response.code, None, response_json

    except urllib.error.URLError as exception:
        # Request error.
        return response_code, str(exception.reason), {}

    except json.JSONDecodeError as exception:
        # Response did not contain valid JSON.
        return response_code, exception.msg, {}

    except UnicodeDecodeError as exception:
        # Improper response encoding.
        return response_code, exception.reason, {}

    except Exception as exception:
        # Generally FUBAR
        return response_code, str(exception), {}

def whoami() -> int:
    """
    Calls the WHOAMI integration api, printing information
    about the current user such as userID and username.
    """

    # Make request.
    status, error, jsonData = apiRequest("/integration/whoami")
    if error is not None:
        print(f"WHOAMI request failed ({status}): {error}")
        sys.exit(API_ERROR)

    # Print who's hacking.
    print(jsonData["message"])
    return 0

def solve(args : argparse.Namespace) -> int:
    """
    Calls the SOLVE integration api, printing information
    about the submission attempt.
    """

    # Check for practice flag.
    if args.flag in ["pwn.college{practice}", "practice"]:
        print("This is the practice flag!\n\nStart the challenge again in normal mode to get the real flag.\n(You can do this here with \"dojo restart -N\")")
        return INCORRECT

    # Make request.
    print(f"Submitting the flag: {args.flag}")
    status, error, jsonData = apiRequest(
        "/integration/solve",
        method="POST",
        args={
            "submission" : args.flag
        }
    )
    if error is not None:
        print(f"SOLVE request failed ({status}): {error}")
        return API_ERROR

    # Print if the flag was correct.
    if jsonData["success"]:
        print("Successfully solved the challenge!"
              if jsonData["status"] == "solved" else
              "Challenge has already been solved!")
    else:
        error = jsonData.get("status", None) # flag is incorrect
        if error is None:
            error = jsonData.get("error")    # challenge does not exist (rare)
        print(f"Flag submission failed: {error}")
        return INCORRECT

    return 0

def restart(args : argparse.Namespace) -> int:
    """
    Calls the START integration api configured to
    use the current challenge.
    """

    # Check what mode to restart in.
    if args.privileged:
        mode = "privileged"
    elif args.normal:
        mode = "normal"
    else:
        mode = "current"

    # Make request.
    print(f"Restarting current challenge in {mode} mode.")
    status, error, jsonData = apiRequest(
        "/integration/start",
        method="POST",
        args={
            "use_current_challenge": True,
            "mode": mode
        }
    )
    if error is not None:
        print(f"START request failed ({status}): {error}")
        return API_ERROR
    
    # Check for success.
    if not jsonData.get("success", False):
        print(f"Failed to restart challenge:\n{jsonData.get("error", "Unspecified error.")}")
        return START_FAILED

    # The impossible restart message.
    print("Restarted? (not sure how you're seeing this)")
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

    submit_parser = subparsers.add_parser(
        name="submit",
        help="Makes a submission attempt for the current running challenge."
    )
    submit_parser.add_argument(
        "flag",
        help="Flag to submit.",
        type=str
    )

    restart_parser = subparsers.add_parser(
        name="restart",
        help="Restart the current challenge. Restarts in the current mode by default."
    )
    restart_parser.add_argument(
        "--privileged",
        "--practice",
        "-P",
        action="store_true", # By default, do not switch to privileged.
        help="Restart in privileged mode."
    )
    restart_parser.add_argument(
        "--normal",
        "-N",
        action="store_true", # By default, do not switch to normal.
        help="Restart in normal mode."
    )

    args = parser.parse_args()

    if args.command is None:
        parser.print_help()
        return INCORRECT_USAGE

    if args.command.lower() == "whoami":
        return whoami()
    
    if args.command.lower() == "submit":
        return solve(args)
    
    if args.command.lower() == "restart":
        return restart(args)

    parser.print_help()
    return INCORRECT_USAGE

if __name__ == "__main__":
    sys.exit(main())

''
