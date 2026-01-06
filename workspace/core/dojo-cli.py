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

def get_token() -> str | None:
    return os.environ.get("DOJO_AUTH_TOKEN")

def apiRequest(endpoint: str, method: str = "GET", args: dict[str, str] = {}) -> tuple[int, str | None, dict[str, str]]:
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
    try:
        response = urllib.request.urlopen(request, timeout=5.0)
    except urllib.error.HTTPError as exception:
        try:
            return exception.code, json.loads(exception.read().decode())["error"], {}
        except:
            return exception.code, exception.reason, {}
    except urllib.error.URLError as exception:
        return 0, exception.reason, {}

    # Parse response.
    try:
        response_json = json.loads(response.read().decode())
    except json.JSONDecodeError as exception:
        return response.status, exception.msg, {}
    except UnicodeDecodeError as exception:
        return response.status, exception.reason, {}
    except Exception as exception:
        return response.status, "Exception while parsing reponse.", {}

    if not response_json.get("success", False):
        error = response_json.get("error", "No message provided.")
        return response.status, error, response_json

    return response.status, None, response_json

def whoami() -> int:
    """
    Calls the WHOAMI integration api, printing information
    about the current user such as userID and username.
    """

    # Make request.
    status, error, jsonData = apiRequest("/user/me")
    if error is not None:
        print(f"WHOAMI request failed ({status}): {error}")
        sys.exit(API_ERROR)

    # Print who's hacking.
    print(f"You are the epic hacker {jsonData["name"]} ({jsonData["id"]}).")
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

    if args.command is None:
        parser.print_help()
        return INCORRECT_USAGE

    if args.command.lower() == "whoami":
        return whoami()

    parser.print_help()
    return INCORRECT_USAGE

if __name__ == "__main__":
    sys.exit(main())
