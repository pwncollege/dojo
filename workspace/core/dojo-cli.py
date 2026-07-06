import argparse
import os
import sys
import requests
import re
import asyncio
from typing import Any, Literal, Optional
from enum import Enum

DOJO_API = "http://pwn.college:80/pwncollege_api/v1"
DOJO_AUTH_TOKEN = os.environ.get("DOJO_AUTH_TOKEN")

# Dojo Client

class Position:
    dojo: str
    module: str
    challenge: str

    def __init__(self, dojo: str, module: str, challenge: str):
        self.dojo = dojo
        self.module = module
        self.challenge = challenge

DojoMode = Literal["normal", "privileged"]

class DojoNotFound(Exception):
    pass
class ModuleNotFound(Exception):
    pass
class ChallengeNotFound(Exception):
    pass
class PrivilegedDisabled(Exception):
    pass
class ChallengeLocked(Exception):
    pass
class DockerFailed(Exception):
    pass

class DojoClient:
    _current_challenge: Optional[Position]
    _current_mode: Optional[DojoMode]

    def __init__(self):
        self._current_challenge = None
        self._current_mode = None

    def get(self, url: str) -> requests.Response:
        return requests.get(url, headers = {"Authorization": f"Bearer {DOJO_AUTH_TOKEN}"}, timeout = 5.0)

    def post(self, url: str, json: dict = {}) -> requests.Response:
        return requests.post(url, json = json, headers = {"Authorization": f"Bearer {DOJO_AUTH_TOKEN}"}, timeout = 5.0)

    def get_current(self) -> tuple[Position, DojoMode]:
        # Cache our current challenge if we need to get this info several times.
        if not self._current_challenge or not self._current_mode:
            response = self.get(f"{DOJO_API}/docker").json()
            self._current_challenge = Position(
                response["dojo"],
                response["module"],
                response["challenge"]
            )
            self._current_mode = "privileged" if response["privileged"] else "normal"
        return self._current_challenge, self._current_mode

    def start(self, challenge: Position, mode: DojoMode):
        response = self.post(
            f"{DOJO_API}/docker",
            json = {
                "dojo": challenge.dojo,
                "module": challenge.module,
                "challenge": challenge.challenge,
                "practice": mode == "privileged"
            }
        ).json()
        error = response["error"]
        match error:
            case "Invalid dojo": raise DojoNotFound(error)
            case "Invalid challenge": raise ChallengeNotFound(error)
            case "This challenge does not support practice mode.": raise PrivilegedDisabled(error)
            case "This challenge is locked": raise PrivilegedDisabled(error)
            case "Docker failed": raise DockerFailed(error)

    def solve(self, challenge: Position, flag: str) -> Literal["correct", "incorrect", "solved", "practice"]:
        if flag == "pwn.college{practice}":
            return "practice"
        response = self.post(
            f"{DOJO_API}/dojos/{challenge.dojo}/{challenge.module}/{challenge.challenge}/solve",
            json = {"submission" : flag}
        ).json()
        match response.get("status"):
            case "solved": return "correct"
            case "already_solved": return "solved"
            case "incorrect": return "incorrect"
            case _: raise ChallengeNotFound(response.get("error", "unknown"))

client = DojoClient()

# Dojo TUI

class Challenge:
    id: str
    name: str
    description: str
    required: bool

    def __init__(
            self,
            id: str,
            name: str,
            description: str,
            required: bool):
        self.id = id
        self.name = name
        self.description = description
        self.required = required

    # TODO extra stats, such as solved, locked, etc.

class Module:
    id: str
    name: str
    description: str
    _challenges: dict[str, Challenge] = {}

    def __init__(
            self,
            id: str,
            name: str,
            description: str,
            challenges: list[Challenge]):
        self.id = id
        self.name = name
        self.description = description
        for challenge in challenges:
            self._challenges[challenge.id] = challenge

    async def challenges(self) -> list[Challenge]:
        # async to make usage consistent with other layers.
        return [challenge for challenge in self._challenges.values()]
    
    async def get(self, challenge: str) -> Optional[Challenge]:
        return self._challenges.get(challenge)

class Dojo:
    id: str
    name: str
    description: str
    type: str
    module_count: int
    challenge_count: int
    _modules: dict[str, Module] = {}
    _lock = asyncio.Lock()

    def __init__(
            self,
            id: str,
            name: str,
            description: str,
            type: str,
            module_count: int,
            challenge_count: int):
        self.id = id
        self.name = name
        self.description = description
        self.type = type
        self.module_count = module_count
        self.challenge_count = challenge_count

    async def modules(self) -> list[Module]:
        async with self._lock:
            if not self._modules:
                self._populate()
            return [module for module in self._modules.values()]

    async def get(self, module: str) -> Optional[Module]:
        async with self._lock:
            if not self._modules:
                self._populate()
            return self._modules.get(module)

    def _populate(self):
        response = client.get(f"{DOJO_API}/dojos/{self.id}/modules")
        modules = response.json()["modules"]
        for module in modules:
            self._modules[module["id"]] = Module(
                module["id"],
                module["name"],
                module["description"],
                [
                    Challenge(
                        challenge["id"],
                        challenge["name"],
                        challenge["description"],
                        challenge["required"],
                    ) for challenge in module["challenges"]
                ]
            )

class PwnCollege:
    _categorized_dojos: dict[str, list[Dojo]] = {}
    _dojos: dict[str, Dojo] = {}
    _lock = asyncio.Lock()

    def __init__(self):
        pass

    async def dojos(self, category: Optional[str] = None) -> list[Dojo]:
        async with self._lock:
            if not self._categorized_dojos:
                self._populate()
            if category:
                return self._categorized_dojos.get(category, [])
            result = []
            return [dojo for dojo in self._dojos.values()]

    async def categories(self) -> list[str]:
        async with self._lock:
            if not self._categorized_dojos:
                self._populate()
            return [key for key in self._categorized_dojos.keys()]

    async def get(self, dojo: str) -> Optional[Dojo]:
        async with self._lock:
            if not self._categorized_dojos:
                self._populate()
            return self._dojos.get(dojo)

    def _populate(self):
        response = client.get(f"{DOJO_API}/dojos")
        dojos = response.json()["dojos"]
        for dojo in dojos:
            self._categorized_dojos.setdefault(dojo["type"], []).append(Dojo(
                dojo["id"],
                dojo["name"],
                dojo["description"],
                dojo["type"],
                dojo["modules_count"],
                dojo["challenges_count"]
            ))

pwn = PwnCollege()

# TODO

# Dojo CLI

class CLI:
    @staticmethod
    def whoami():
        response = client.get(f"{DOJO_API}/users/me")
        data = response.json()
        if not response.ok:
            sys.exit(data.get("error", "Unknown error"))
        print(f"You are the epic hacker {data['name']} ({data['id']}).")

    @staticmethod
    def solve(args : argparse.Namespace):
        print(f"Submitting the flag: {args.flag}")
        challenge, _ = client.get_current()
        result = client.solve(challenge, args.flag)
        match result:
            case "correct":
                print("Successfully solved the challenge!")
                sys.exit(0)
            case "incorrect":
                sys.exit("Incorrect flag.")
            case "solved":
                print("Challenge has already been solved!")
                sys.exit(0)
            case "practice":
                sys.exit("This is the practice flag!\n\nStart the challenge again in normal mode to get the real flag.\n(You can do this here with \"dojo restart -N\")")

    @staticmethod
    def restart(args : argparse.Namespace):
        challenge, mode = client.get_current()
        if args.privileged:
            mode = "privileged"
        elif args.normal:
            mode = "normal"
        client.start(challenge, mode)

    @staticmethod
    def parse_dojo_path(path:str) -> Position:
        if result := re.match(r"^/?([a-z0-9-~]{1,128})/([a-z0-9-~]{1,128})/([a-z0-9-~]{1,128})$", path):
            return Position(result.group(1), result.group(2), result.group(3))
        else:
            challenge, _ = client.get_current()
        
        if result := re.match(r"^([a-z0-9-~]{1,128})/([a-z0-9-~]{1,128})", path):
            return Position(challenge.dojo, result.group(1), result.group(2))
        elif result := re.match(r"^([a-z0-9-~]{1,128})", path):
            return Position(challenge.dojo, challenge.module, result.group(1))

        raise Exception(f"Cannot parse path {path}")

    @staticmethod
    def start(args : argparse.Namespace):
        try:
            challenge = parse_dojo_path(args.challenge)
            client.start(challenge, "privileged" if args.privileged else "normal")
        except Exception as e:
            sys.exit(f"Incorrect path format, see \"dojo start -h\" for more information.\n{str(e)}")

    @staticmethod
    def list_dojos(types: list[str], use_expanded_format: bool):
        if not use_expanded_format:
            print(" ".join(dojo.id for dojo in asyncio.run(pwn.dojos())))
            sys.exit(0)

        type_names = {
            "welcome": "Welcome",
            "topic": "Official",
            "public": "Community",
            "course": "Course"
        }
        for type in types:
            dojo_list = asyncio.run(pwn.dojos(type))
            print(f"{type_names.get(type, type)}: {len(dojo_list)}")
            if (len(dojo_list) == 0):
                print("")
                continue
            print(f"{"Modules":<10}{"Challenges":<15}id (name)")
            for dojo in dojo_list:
                print(f"{dojo.module_count:<10}{dojo.challenge_count:<15}{dojo.id} ({dojo.name})")
            print("")

    @staticmethod
    def list_modules(dojo_id: str, use_expanded_format: bool):
        dojo = asyncio.run(pwn.get(dojo_id))
        if not dojo:
            raise DojoNotFound(f"No such dojo {dojo_id}.")
        modules = asyncio.run(dojo.modules())

        if not use_expanded_format:
            print(" ".join([module.id for module in modules]))
            sys.exit(0)

        print(f"Dojo: {dojo_id}")
        print("")
        print(f"Total: {len(modules)}")
        print(f"{"Challenges":<15}id (name)")
        for module in modules:
            print(f"{len(asyncio.run(module.challenges())):<15}{module.id} ({module.name})")

    @staticmethod
    def list_challenges(dojo_id: str, module_id: str, use_expanded_format: bool):
        dojo = asyncio.run(pwn.get(dojo_id))
        if not dojo:
            raise DojoNotFound(f"No such dojo {dojo_id}.")
        module = asyncio.run(dojo.get(module_id))
        if not module:
            raise ModuleNotFound(f"No such module {module_id} in dojo {dojo_id}")
        challenges = asyncio.run(module.challenges())

        if not use_expanded_format:
            print(" ".join(challenge.id for challenge in challenges))
            sys.exit(0)

        print(f"Dojo: {dojo_id}")
        print(f"Module: {module_id}")
        print("")
        print(f"id (name)")
        for challenge in challenges:
            print(f"{"[optional] " if not challenge.required else ""}{challenge.id} ({challenge.name})")

    @staticmethod
    def list(args: argparse.Namespace):
        """
        Lists out dojos, modules, or challenges depending on path.
        """
        if not args.path:
            challenge, _ = client.get_current()
            CLI.list_challenges(challenge.dojo, challenge.module, args.l)
        elif re.match(r"^/$", args.path):
            types = []
            if args.welcome or args.all:
                types.append("welcome")
            if args.official or args.all:
                types.append("topic")
            if args.community or args.all:
                types.append("public")
            if args.course or args.all:
                types.append("course")
            if len(types) == 0:
                types = ["welcome", "topic"] # default types
            CLI.list_dojos(types, args.l)
        elif re.match(r"^/[a-z0-9-~]{1,128}$", args.path):
            dojo = args.path[1:]
            CLI.list_modules(dojo, args.l)
        elif re.match(r"^/[a-z0-9-~]{1,128}/[a-z0-9-]{1,32}$", args.path):
            CLI.list_challenges(args.path.split("/")[1], args.path.split("/")[2], args.l)
        else:
            sys.exit("Dojo path must match one of \"/\", \"/<dojo>\", or \"/<dojo>/<module>\".")

def main():
    parser = argparse.ArgumentParser(
        prog="dojo",
        description="CLI & TUI for interacting with the dojo from inside of the challenge environment.",
    )
    subparsers = parser.add_subparsers(
        dest="command",
        help="Dojo command to execute."
    )
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
    list_parser = subparsers.add_parser(
        name="list",
        help="List dojos, modules, or challenges using a dojo path."
    )
    list_parser.add_argument(
        "--official",
        "-O",
        action="store_true",
        help="Show official (non-course) dojos." # Internally, topic dojos
    )
    list_parser.add_argument(
        "--welcome",
        "-W",
        action="store_true",
        help="Show welcome dojos."
    )
    list_parser.add_argument(
        "--course",
        "-E",#education
        action="store_true",
        help="Show course dojos."
    )
    list_parser.add_argument(
        "--community",
        "-C",
        action="store_true",
        help="Show community dojos."
    )
    list_parser.add_argument(
        "--all",
        "-a",
        "-A",
        action="store_true",
        help="Show all dojos (shorthand for -OWEC)"
    )
    list_parser.add_argument(
        "-l",
        action="store_true",
        help="Show extended list information."
    )
    list_parser.add_argument(
        "path",
        help="Dojo path. Can be /, /<dojo>, or /<dojo>/<module>.",
        nargs="?",
        type=str
    )
    args = parser.parse_args()
    if not DOJO_AUTH_TOKEN:
        sys.exit("Missing DOJO_AUTH_TOKEN.")
    if not args.command:
        # TUI goes here
        print("TUI is on the way!")
        sys.exit(0)
    if args.command == "whoami":
        CLI.whoami()
    if args.command == "submit":
        CLI.solve(args)
    if args.command == "restart":
        CLI.restart(args)
    if args.command == "start":
        CLI.start(args)
    if args.command == "list":
        CLI.list(args)
    else:
        parser.print_help()
        sys.exit(1)

if __name__ == "__main__":
    main()
