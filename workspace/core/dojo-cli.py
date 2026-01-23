import argparse
import os
import sys
import requests
from typing import Any

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

def get_current_challenge() -> dict[str, str]:
    response = requests.get(
        f"{DOJO_API}/docker",
        headers={"Authorization": f"Bearer {DOJO_AUTH_TOKEN}"},
        timeout = 5.0
    )
    if not response.ok:
        sys.exit("Failed to get the current challenge.")
    return response.json()

def solve(args : argparse.Namespace):
    # Check for practice flag.
    if args.flag in ["pwn.college{practice}", "practice"]:
        sys.exit("This is the practice flag!\n\nStart the challenge again in normal mode to get the real flag.\n(You can do this here with \"dojo restart -N\")")

    # Submit the flag to the current challenge.
    print(f"Submitting the flag: {args.flag}")
    challenge = get_current_challenge()
    response = requests.get(
        f"{DOJO_API}/dojos/{challenge["dojo"]}/{challenge["module"]}/{challenge["challenge"]}/solve",
        headers={"Authorization": f"Bearer {DOJO_AUTH_TOKEN}"},
        json={
            "submission": args.flag
        },
        timeout = 5.0
    )
    result = response.json()

    # Print if the flag was correct.
    if result["success"]:
        print("Successfully solved the challenge!"
              if result["status"] == "solved" else
              "Challenge has already been solved!")
        sys.exit(0)
    else:
        sys.exit("Incorrect flag.")

def start_challenge(dojo:str, module:str, challenge:str, privileged:bool):
    response = requests.post(
        f"{DOJO_API}/docker",
        headers={"Authorization": f"Bearer {DOJO_AUTH_TOKEN}"},
        json={
            "dojo": dojo,
            "module": module,
            "challenge": challenge,
            "practice": privileged
        },
        timeout=5.0
    )

    # How did we get here?
    result = response.json()
    if not (result["success"]):
        sys.exit(result["error"])
    print("Started challenge.")
    sys.exit(0)

def restart(args : argparse.Namespace):
    """
    Calls the START integration api configured to
    use the current challenge.
    """
    challenge = get_current_challenge()
    if args.privileged:
        privileged = True
    elif args.normal:
        privileged = False
    else:
        privileged = bool(challenge["practice"])
    start_challenge(challenge["dojo"], challenge["module"], challenge["challenge"], privileged)

def parse_dojo_path(path:str) -> dict[Any, Any]:
    """
    Parses a dojo path.
    """
    if len(path) == 0:
        raise Exception("Dojo path cannot be empty.")

    # Parse as an absolute path.
    if path[0] == "/":
        path = path.removesuffix("/")
        components = path.split("/")
        match len(components):
            case 2:
                return {"dojo": components[1], "module": None, "challenge": None}
            case 3:
                return {"dojo": components[1], "module": components[2], "challenge": None}
            case 4:
                return {"dojo": components[1], "module": components[2], "challenge": components[3]}
            case _:
                raise Exception("An absolute dojo path can have between one and three levels.")
    # Parse as relative path (to current challenge).
    else:
        challenge = get_current_challenge()
        components = path.split("/")
        match len(components):
            case 1:
                return {"dojo": challenge["dojo"], "module": challenge["module"], "challenge": components[0]}
            case 2:
                return {"dojo": challenge["dojo"], "module": components[0], "challenge": components[1]}
            case 3:
                return {"dojo": components[0], "module": components[1], "challenge": components[2]}
            case _:
                raise Exception("A relative dojo path can have between one and three levels.")

def start(args : argparse.Namespace):
    """
    Calls the START integration api configured to
    start a new challenge.
    """

    # Determine what challenge to start.
    try:
        path = parse_dojo_path(args.challenge)
        if (None in path.values()):
            raise Exception("Absolute paths must be complete for starting challenges.")
        start_challenge(path["dojo"], path["module"], path["challenge"], bool(args.privileged))
    except Exception as e:
        sys.exit(f"Incorrect path format, see \"dojo start -h\" for more information.\n{str(e)}")


def main():
    parser = argparse.ArgumentParser(
        prog="dojo",
        description="Command-line application for interacting with the dojo from inside of the challenge environment.",
    )
    subparsers = parser.add_subparsers(dest="command", help="Dojo command to execute, not case sensitive.")
    subparsers.add_parser(name="whoami", help="Prints information about the current user (you!).")
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
    start_parser = subparsers.add_parser(
        name="start",
        help="Start a new challenge. Restarts in normal mode by default."
    )
    start_parser.add_argument(
        "--privileged",
        "--practice",
        "-P",
        action="store_true", # By default, do not start in privileged mode.
        help="Start challenge in privileged mode."
    )
    start_parser.add_argument(
        "challenge",
        help="Challenge to start. Can be <challenge> or /<dojo>/<module>/<challenge>.",
        type=str
    )
    args = parser.parse_args()
    if not DOJO_AUTH_TOKEN:
        sys.exit("Missing DOJO_AUTH_TOKEN.")
    if not args.command:
        parser.print_help()
        sys.exit(1)
    if args.command.lower() == "whoami":
        return whoami()
    if args.command.lower() == "submit":
        return solve(args)
    if args.command.lower() == "restart":
        return restart(args)
    if args.command.lower() == "start":
        return start(args)
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
