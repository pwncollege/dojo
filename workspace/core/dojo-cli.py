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

def solve(args : argparse.Namespace) -> int:
    # Check for practice flag.
    if args.flag in ["pwn.college{practice}", "practice"]:
        sys.exit("This is the practice flag!\n\nStart the challenge again in normal mode to get the real flag.\n(You can do this here with \"dojo restart -N\")")

    # Get current challenge.
    print(f"Submitting the flag: {args.flag}")
    challenge_response = requests.get(
        f"{DOJO_API}/docker",
        headers={"Authorization": f"Bearer {DOJO_AUTH_TOKEN}"},
        timeout = 5.0
    )
    if not challenge_response.ok:
        sys.exit("Failed to get the current challenge.")
    challenge_json = challenge_response.json()
    submission_response = requests.get(
        f"{DOJO_API}/{challenge_json["dojo"]}/{challenge_json["module"]}/{challenge_json["challenge"]}/solve",
        headers={"Authorization": f"Bearer {DOJO_AUTH_TOKEN}"},
        json={
            "submission": args.flag
        },
        timeout = 5.0
    )
    submission_json = submission_response.json()

    # Print if the flag was correct.
    if submission_json["success"]:
        print("Successfully solved the challenge!"
              if submission_json["status"] == "solved" else
              "Challenge has already been solved!")
        sys.exit(0)
    else:
        sys.exit("Incorrect flag.")

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

def start(args : argparse.Namespace) -> int:
    """
    Calls the START integration api configured to
    start a new challenge.
    """

    # Determine what challenge to start.
    mode = "privileged" if args.privileged else "normal"
    if len(args.challenge) == 0:
        print("Must supply a valid challenge. See \"dojo start -h\" for more information.")
        return INCORRECT_USAGE

    if args.challenge[0] == "/": # parse as a /<dojo>/<module>/<challenge> path.
        path = args.challenge.split("/")
        if len(path) != 4:
            print("Challenge paths beginning with \"/\" must follow the form /<dojo>/<module>/<challenge>.")
            return INCORRECT_USAGE
        jsonargs = {
            "dojo": path[1],
            "module": path[2],
            "challenge": path[3],
            "mode": mode
        }
    else: # parse as a challenge in the current module.
        jsonargs = {
            "use_current_module": True,
            "challenge": args.challenge,
            "mode": mode
        }

    # Make request.
    print(f"Starting {jsonargs["challenge"]} in {mode} mode.")
    status, error, jsonData = apiRequest(
        "/integration/start",
        method="POST",
        args=jsonargs
    )
    if error is not None:
        print(f"START request failed ({status}): {error}")
        return API_ERROR

    # Check for success.
    if not jsonData.get("success", False):
        print(f"Failed to start challenge:\n{jsonData.get("error", "Unspecified error.")}")
        return START_FAILED

    # Impossible?
    print("Started challenge. (How did we get here?)")
    return 0


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
