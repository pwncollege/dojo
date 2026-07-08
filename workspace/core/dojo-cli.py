import argparse
import os
import sys
import requests
import re
import asyncio
from textual import work
from textual.reactive import reactive
from textual.app import App, ComposeResult
from textual.screen import Screen, ModalScreen
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, Grid, Container
from textual.widget import Widget
from textual.widgets import Footer, Header, Markdown, Static, Tree, OptionList, Label, Button
from textual.widgets.option_list import Option
from textual.worker import Worker, get_current_worker
from textual.widgets.tree import TreeNode
from typing import Literal, Optional

DOJO_API = "http://pwn.college:80/pwncollege_api/v1"
DOJO_AUTH_TOKEN = os.environ.get("DOJO_AUTH_TOKEN")

VERSION = "0.1"
UPDATED = "2026-07-07"

DOJO_DESCRIPTION = """You have entered the pwn.college DOJO, an education platform for learners to develop and practice core cybersecurity skills in a hands-on fashion. Entering, you receive your "white belt" , signifying the beginning of your hacker life. From here, you will learn cybersecurity by diving deep into the core of computing, using that journey to absorb cybersecurity concepts. This will involve melding your mind to your terminal, whispering instructions to the CPU, and strumming bits directly onto networks. That terminal cursor blinking above? It will be your stalwart companion through this adventure as you practice, earn your [belts](https://pwn.college/belts) , and, eventually, make perfect.

Every dojo has its sensei. This platform is maintained by an [awesome team](https://pwn.college/sensei) of hackers at Arizona State University. It powers much of ASU's cybersecurity curriculum, and is open, for free, to participation for interested people around the world!

Enjoy your journey! If you have questions, comments, suggestions, and feedback, please join our [Discord](https://discord.gg/pwncollege) server or email us at [pwn@pwn.college](pwn@pwn.college)!"""

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
            self._current_mode = "privileged" if response["practice"] else "normal"
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
        error = response.get("error")
        if not error:
            return
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

# Dojo Crawling

# TODO: can(should) we add some cache to not wait for API requests every time we want to crawl the dojo?

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
    _challenges: dict[str, Challenge]

    def __init__(
            self,
            id: str,
            name: str,
            description: str,
            challenges: list[Challenge]):
        self.id = id
        self.name = name
        self.description = description
        self._challenges = {}
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
    _modules: dict[str, Module]
    _lock: asyncio.Lock

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
        self._modules = {}
        self._lock = asyncio.Lock()

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
    _categorized_dojos: dict[str, list[Dojo]]
    _dojos: dict[str, Dojo]
    _lock: asyncio.Lock

    def __init__(self):
        self._categorized_dojos = {}
        self._dojos = {}
        self._lock = asyncio.Lock()

    async def dojos(self, category: Optional[str] = None) -> list[Dojo]:
        async with self._lock:
            if not self._categorized_dojos:
                self._populate()
            if category:
                return self._categorized_dojos.get(category, [])
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
            dojo_obj = Dojo(
                dojo["id"],
                dojo["name"],
                dojo["description"],
                dojo["type"],
                dojo["modules_count"],
                dojo["challenges_count"]
            )
            self._categorized_dojos.setdefault(dojo["type"], []).append(dojo_obj)
            self._dojos[dojo_obj.id] = dojo_obj

pwn = PwnCollege()

# Dojo TUI

class DojoInfo(Widget):
    path = reactive("")

    DEFAULT_CSS = """
    DojoInfo {
        margin: 1;
    }

    #title {
        text-style: bold;
    }
    """

    def watch_path(self, new_path: str):
        self.update_contents()

    @work(exclusive = True, thread = True)
    async def update_contents(self):
        if self.path == "":
            return
        worker = get_current_worker()
        title = self.query_one("#title", Static)
        path = self.query_one("#path", Static)
        description = self.query_one("#description", Markdown)
        self.app.call_from_thread(path.update, self.path)
        try:
            # There must be... a better way.
            if re.match(r"^/$", self.path):
                title_text = "Welcome to pwn.college"
                # TODO remember to replace this.
                description_text = DOJO_DESCRIPTION
            elif result := re.match(r"^/([a-z0-9-~]{1,128})$", self.path):
                dojo = await pwn.get(result.group(1))
                if not dojo: raise DojoNotFound()
                title_text = dojo.name
                description_text = dojo.description
            elif result := re.match(r"^/([a-z0-9-~]{1,128})/([a-z0-9-]{1,32})$", self.path):
                dojo = await pwn.get(result.group(1))
                if not dojo: raise DojoNotFound()
                module = await dojo.get(result.group(2))
                if not module: raise ModuleNotFound()
                title_text = module.name
                description_text = module.description
            elif result := re.match(r"^/([a-z0-9-~]{1,128})/([a-z0-9-]{1,32})/([a-z0-9-]{1,32})$", self.path):
                dojo = await pwn.get(result.group(1))
                if not dojo: raise DojoNotFound()
                module = await dojo.get(result.group(2))
                if not module: raise ModuleNotFound()
                challenge = await module.get(result.group(3))
                if not challenge: raise ChallengeNotFound()
                title_text = challenge.name
                description_text = challenge.description
            else:
                title_text = "ERROR - bad path"
                description_text = f"Unable to parse the path `{self.path}`"
        except DojoNotFound:
                title_text = "ERROR - bad path"
                description_text = f"Unable to parse the path `{self.path}`, no such dojo found."
        except ModuleNotFound:
                title_text = "ERROR - bad path"
                description_text = f"Unable to parse the path `{self.path}`, no such module found."
        except ChallengeNotFound:
                title_text = "ERROR - bad path"
                description_text = f"Unable to parse the path `{self.path}`, no such challenge found."
        if not worker.is_cancelled:
            self.app.call_from_thread(path.update, self.path)
            self.app.call_from_thread(title.update, title_text)
            self.app.call_from_thread(description.update, description_text if description_text else "No description provided :(")

    def compose(self) -> ComposeResult:
        # Title & description updated in the background.
        yield Static("Loading...", id = "title")
        yield Static("Loading...", id = "path")
        yield Static("")
        yield Markdown("Loading...", id = "description")

class Hub(Screen):
    CSS = """
    #body {
        height: 100%;
    }

    #options {
        dock: bottom;
        margin-bottom: 1;
    }
    
    DojoInfo {
        height: auto;
    }
    """
    # Shows information about the current challenge, and allows for navigation to other screens.
    def compose(self) -> ComposeResult:
        yield Header()
        with Vertical(id = "body"):
            yield DojoInfo(id = "info")
            yield OptionList(
                Option("Start a Challenge", id = "start"),
                Option("Submit a Flag", id = "submit"),
                Option("TUI Info", id = "about"),
                Option("Settings", id = "settings"),
                Option("Quit", id = "quit"),
                id = "options"
            )
        yield Footer()

    def on_mount(self):
        async def set_current():
            challenge, _ = client.get_current()
            self.query_one("#info", DojoInfo).path = f"/{challenge.dojo}/{challenge.module}/{challenge.challenge}"
        self.run_worker(set_current(), thread = True)

    def on_option_list_option_selected(self, event: OptionList.OptionSelected):
        if event.option_id == "quit":
            return self.app.exit()
        self.app.switch_mode(event.option_id if event.option_id else "hub")

class StartModal(ModalScreen):
    challenge_path: str
    challenge_name: str
    allow_privileged: bool

    # hard-coding the sizes because alignment styles don't seem to be working.
    CSS = """
    StartModal {
        width: 100%;
        height: 100%;
        align: center middle;
    }

    #modal {
        width: 80;
        height: 7;
        padding: 1;
        align: center middle;
    }

    #challenge {
        width: 100%;
        height: 1;
        content-align: center middle;
    }

    #buttons {
        width: 100%;
        height: 5;
        content-align: center middle;
        padding: 1;
    }

    Button {
        height: 3;
        width: 1fr;
    }
    """

    BINDINGS = [("escape", "app.pop_screen()", "Cancel")]

    def __init__(self, challenge_path: str, challenge_name: str, allow_privileged: bool, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.challenge_path = challenge_path
        self.challenge_name = challenge_name
        self.allow_privileged = allow_privileged

    def compose(self) -> ComposeResult:
        with Container(id = "modal"):
            yield Label(f"Starting challenge {self.challenge_name}", id = "challenge")
            with Horizontal(id = "buttons"):
                yield Button("Normal", id = "normal")
                if self.allow_privileged:
                    yield Label("  ")
                    yield Button("Privileged", id = "privileged")

    def on_button_pressed(self, event: Button.Pressed):
        result = re.match(r"^/([a-z0-9-~]{1,128})/([a-z0-9-]{1,32})/([a-z0-9-]{1,32})$", self.challenge_path)
        client.start(Position(result.group(1), result.group(2), result.group(3)), event.button.id) # type: ignore

class DojoBrowser(Widget):
    dojos: Tree[str]
    _worker_lock: asyncio.Lock # not sure this is the correct lock to use here

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._worker_lock = asyncio.Lock()
        self.dojos = Tree("dojos", "1")
        self.dojos.show_root = False

    @work() # Don't make this a threaded task, we want to make sure we at least have categories.
    async def _populate_dojos(self):
        # TODO make this an option somewhere idk
        show_hidden = False
        ordered_named_categories = [
            ("welcome", "Welcome", True),
            ("topic", "Official", True),
            ("course", "Course", True),
            ("public", "Community", True),
            ("private", "Private", False),
            ("example", "Example", False),
            ("hidden", "Hidden", False)
        ]
        categories = await pwn.categories()
        for id, name, visible in ordered_named_categories:
            if id not in categories:
                continue
            if not visible and not show_hidden:
                continue
            folder = self.dojos.root.add(name, f"1{id}")
            dojos = await pwn.dojos(id)
            for dojo in dojos:
                dummy = folder.add(dojo.name, f"2{dojo.id}").add("Loading...", "0")
                dummy.allow_expand = False

    @work(thread = True, exclusive = True, group = "info_update")
    async def _update_info(self, node: TreeNode):
        worker = get_current_worker()
        info = self.screen.query_one("#info", DojoInfo)
        path = self.get_path(node)
        if not worker.is_cancelled:
            info.path = path

    def get_path(self, node: TreeNode) -> str:
        steps = int(node.data[:1]) # type: ignore - we assume this is correctly set.
        path = ""
        if steps == 1:
            path = "/"
        elif steps > 1:
            for _ in range(steps - 1):
                path = f"/{node.data[1:]}" + path # type: ignore
                node = node.parent # type: ignore
        return path

    @work(thread = True)
    async def _populate_dojo(self, dojo_node: TreeNode):
        # Avoid race condition if node is highlighted twice.
        async with self._worker_lock:
            child = dojo_node.children[0]
            if child.data != "0":
                return
            else:
                child.data = "0WORKING"
        dojo_id = dojo_node.data[1:] # type: ignore
        dojo = await pwn.get(dojo_id)
        if not dojo:
            dojo_node.children[0].label = "Error: unable to fetch dojo data."
            return
        for module in await dojo.modules():
            new_node = dojo_node.add(module.name, f"3{module.id}")
            for challenge in await module.challenges():
                new_node.add(challenge.name, f"4{challenge.id}", allow_expand = False)
        # Remove the placeholder loading node.
        child.remove()

    def on_tree_node_expanded(self, event: Tree.NodeExpanded):
        # Only called if the node is a dojo node.
        if event.node.data[:1] == "2": # type: ignore
            self._populate_dojo(event.node)

    @work()
    async def pop_modal(self, node: TreeNode):
        path = self.get_path(node)
        result = re.match(r"^/([a-z0-9-~]{1,128})/([a-z0-9-]{1,32})/([a-z0-9-]{1,32})$", path)
        assert result
        dojo = await pwn.get(result.group(1))
        assert dojo
        module = await dojo.get(result.group(2))
        assert module
        challenge = await module.get(result.group(3))
        assert challenge
        self.app.push_screen(StartModal(path, challenge.name, True)) # dojos API does not show if privileged is allowed. was this removed?

    def on_tree_node_selected(self, event: Tree.NodeSelected):
        if event.node.data[:1] == "4": # type: ignore
            self.pop_modal(event.node)

    def on_tree_node_highlighted(self, event: Tree.NodeHighlighted):
        self._update_info(event.node)

    def compose(self) -> ComposeResult:
        yield self.dojos
        self._populate_dojos()

class StartMenu(Screen):
    # Screen for browsing dojos and starting challenges.
    CSS = """
    #browser {
        width: 40%
    }
    #info {
        width: 60%
    }
    """

    BINDINGS = [("escape", "app.switch_mode(\"hub\")", "Return")]

    def compose(self) -> ComposeResult:
        yield Header()
        with Horizontal():
            yield DojoBrowser(id = "browser")
            yield DojoInfo(id = "info")
        yield Footer()

class SubmitMenu(Screen):
    # Screen for submitting flags, with cool animations!
    def compose(self) -> ComposeResult:
        yield Header()
        yield Static("submit")
        yield Footer()

class About(Screen):
    # Screen that shows some information about the TUI and pwn.college
    CSS = """
    #body {
        padding: 1 3;
    }

    #contents {
        padding: 1;
    }
    """

    BINDINGS = [("escape", "app.switch_mode(\"hub\")", "Return")]
    
    def compose(self) -> ComposeResult:
        yield Header()
        with Vertical(id = "body"):
            yield Static("[bold]DOJO TUI/CLI[bold]")
            with Vertical(id = "contents"):
                yield Static("Tool for navigating the pwn.college dojo from within the challenge container.")
                yield Static("For more info about CLI mode, use [bold]dojo -h[bold]")
                yield Static("")
                yield Static(f"Version: [italic]{VERSION}[italic]")
                yield Static(f"Last Updated: [italic]{UPDATED}[italic]")
                yield Static("")
                yield Static("Contributors: Theodor Kitzenmaier")
        yield Footer()

class Settings(Screen):
    # Screen with a few application settings.
    def compose(self) -> ComposeResult:
        yield Header()
        yield Static("settings")
        yield Footer()

class TUI(App):
    MODES = {
        "hub": Hub,
        "start": StartMenu,
        "submit": SubmitMenu,
        "about": About,
        "settings": Settings
    }

    DEFAULT_MODE = "hub"
    
    def on_mount(self) -> None:
        async def set_title():
            challenge, mode = client.get_current()
            self.title = f"/{challenge.dojo}/{challenge.module}/{challenge.challenge}"
            self.sub_title = mode
        self.run_worker(set_title(), thread=True)

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
        app = TUI()
        app.run()
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
