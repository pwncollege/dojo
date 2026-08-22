import os

import requests
from itsdangerous.url_safe import URLSafeTimedSerializer
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.widgets import Footer, Header, Markdown, Static, Tree


SECTION_ORDER = {
    "welcome": 0,
    "topic": 1,
    "public": 2,
    "course": 3,
    "private": 4,
    "hidden": 5,
    "example": 6,
}


def display_name(item, fallback_prefix):
    return item.get("name") or item.get("id") or f"Unnamed {fallback_prefix}"


def sort_dojos(dojos):
    indexed_dojos = list(enumerate(dojos))
    return [
        dojo
        for _, dojo in sorted(
            indexed_dojos,
            key=lambda item: (
                SECTION_ORDER.get(item[1].get("type"), 100),
                item[0],
            ),
        )
    ]


class ChallengeClient:
    def __init__(self):
        self.auth_token = os.environ.get("DOJO_AUTH_TOKEN")
        self.ssh_key = os.environ.get("DOJO_SSH_SERVICE_KEY")
        self.user_id = os.environ.get("DOJO_USER_ID")
        if not self.auth_token and not (self.ssh_key and self.user_id):
            raise RuntimeError("Missing DOJO_AUTH_TOKEN, or DOJO_SSH_SERVICE_KEY and DOJO_USER_ID")
        self.dojo_host = os.environ.get("DOJO_HOST")
        self.api_base = "http://pwn.college:80/pwncollege_api/v1"

    def authorization(self):
        if self.auth_token:
            return f"Bearer {self.auth_token}"
        token = URLSafeTimedSerializer(self.ssh_key).dumps([int(self.user_id), "ssh-tui"])
        return f"Bearer sk-ssh-service-{token}"

    def headers(self):
        headers = {
            "Authorization": self.authorization(),
            "Content-Type": "application/json",
        }
        if self.dojo_host:
            headers["Host"] = self.dojo_host
        return headers

    def get(self, path, key):
        response = requests.get(f"{self.api_base}{path}", headers=self.headers(), timeout=20)
        response.raise_for_status()
        data = response.json()
        if not data.get("success"):
            raise RuntimeError(data.get("error", "Request failed"))
        return data.get(key, [])

    def post(self, path, payload):
        response = requests.post(f"{self.api_base}{path}", headers=self.headers(), json=payload, timeout=60)
        response.raise_for_status()
        data = response.json()
        if not data.get("success"):
            raise RuntimeError(data.get("error", "Request failed"))
        return data

    def load_dojos(self):
        return sort_dojos(self.get("/dojos", "dojos"))

    def load_dojo_modules(self, dojo_id):
        return self.get(f"/dojos/{dojo_id}/modules", "modules")

    def start_challenge(self, dojo_id, module_id, challenge_id, practice):
        self.post(
            "/docker",
            {
                "dojo": dojo_id,
                "module": module_id,
                "challenge": challenge_id,
                "practice": practice,
            },
        )


def dojo_details(dojo):
    lines = [f"# {display_name(dojo, 'dojo')}", ""]
    if dojo.get("description"):
        lines.extend([dojo["description"].strip(), ""])
    lines.extend([
        f"- Dojo ID: `{dojo['id']}`",
        f"- Modules: `{dojo.get('modules_count', 0)}`",
        f"- Challenges: `{dojo.get('challenges_count', 0)}`",
    ])
    return "\n".join(lines)


def module_details(module):
    lines = [f"# {display_name(module, 'module')}", ""]
    if module.get("description"):
        lines.extend([module["description"].strip(), ""])
    challenges = module.get("challenges")
    resources = module.get("resources")
    lines.extend([
        f"- Module ID: `{module['id']}`",
        f"- Challenges: `{len(challenges) if challenges is not None else '?'}`",
        f"- Resources: `{len(resources) if resources is not None else '?'}`",
    ])
    return "\n".join(lines)


def challenge_details(challenge):
    lines = [f"# {display_name(challenge, 'challenge')}", ""]
    if challenge.get("description"):
        lines.extend([challenge["description"].strip(), ""])
    lines.extend([
        f"- Challenge ID: `{challenge['id']}`",
        f"- Required: `{'yes' if challenge.get('required') else 'no' if challenge.get('required') is not None else '?'}`",
        "",
        "Press `enter` to choose a start mode.",
        "Press `s` to start standard mode.",
        "Press `p` to start practice mode.",
    ])
    return "\n".join(lines)


class VimTree(Tree):
    BINDINGS = [
        Binding("j", "vim_down", "Down", show=False),
        Binding("k", "vim_up", "Up", show=False),
        Binding("h", "vim_left", "Collapse", show=False),
        Binding("l", "vim_right", "Expand", show=False),
        Binding("g", "vim_top", "Top", show=False),
        Binding("G", "vim_bottom", "Bottom", show=False),
    ]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._count = ""
        self._pending_g = False

    def on_key(self, event):
        if event.character and event.character.isdigit() and (event.character != "0" or self._count):
            self._count += event.character
            self._pending_g = False
            event.stop()
            event.prevent_default()
            return
        if event.key not in ("j", "k", "h", "l", "g", "G"):
            self._count = ""
        if event.key != "g":
            self._pending_g = False

    def take_count(self):
        count = int(self._count) if self._count else 1
        self._count = ""
        return count

    def move_cursor_by(self, delta):
        self.cursor_line = max(self.cursor_line, 0) + delta
        self.scroll_to_line(self.cursor_line, animate=False)

    def action_vim_down(self):
        self.move_cursor_by(self.take_count())

    def action_vim_up(self):
        self.move_cursor_by(-self.take_count())

    def action_vim_left(self):
        self.take_count()
        node = self.cursor_node
        if node and node.allow_expand and node.is_expanded:
            node.collapse()
        else:
            self.action_cursor_parent()

    def action_vim_right(self):
        self.take_count()
        node = self.cursor_node
        if not node:
            return
        if node.allow_expand and not node.is_expanded:
            node.expand()
        elif node.children:
            self.move_cursor_by(1)

    def action_vim_top(self):
        if not self._pending_g:
            self._pending_g = True
            return
        self._pending_g = False
        self.take_count()
        self.cursor_line = 0
        self.scroll_to_line(self.cursor_line, animate=False)

    def action_vim_bottom(self):
        self.take_count()
        self.cursor_line = self.last_line
        self.scroll_to_line(self.cursor_line, animate=False)


def render_details(data):
    kind = data["kind"]
    if kind == "dojo":
        return dojo_details(data["dojo"])
    if kind == "module":
        return module_details(data["module"])
    if kind == "challenge":
        return challenge_details(data["challenge"])
    return "# Challenge Browser"


class ChallengeBrowserApp(App):
    TITLE = "pwn.college"
    SUB_TITLE = "dojos"

    CSS = """
    Screen {
        background: #000000;
        color: #ffffff;
    }

    Header {
        background: #000000;
        color: #78be20;
        text-style: bold;
    }

    Footer {
        background: #000000;
        color: #00a3e0;
    }

    #body {
        height: 1fr;
    }

    #nav {
        width: 42%;
        min-width: 40;
        border: tall #78be20;
        background: #101010;
    }

    #nav.start-picker {
        border: tall #ffc627;
    }

    #details-pane {
        width: 58%;
        border: tall #00a3e0;
        background: #101010;
    }

    #nav-title, #details-title {
        height: 1;
        padding: 0 1;
        background: #272727;
        color: #ffc627;
        text-style: bold;
    }

    #details-title {
        color: #78be20;
    }

    Tree {
        padding: 0 1;
        color: #ffffff;
    }

    Markdown {
        padding: 0 1;
        color: #ffffff;
    }

    #start-pane, #details {
        height: 1fr;
        overflow-y: auto;
    }

    #status {
        height: 1;
        padding: 0 1;
        background: #272727;
        color: #00a3e0;
    }

    """

    BINDINGS = [
        Binding("q", "quit", "Quit"),
        Binding("r", "reload", "Reload"),
        Binding("escape", "cancel_start", "Back"),
        Binding("s", "start_standard", "Standard"),
        Binding("p", "start_practice", "Practice"),
    ]

    def __init__(self, client, start_error=None):
        super().__init__()
        self.client = client
        self.selection = None
        self.choosing_start = False
        self.start_error = start_error

    def add_loading_node(self, node):
        node.add_leaf("Loading...", {"kind": "loading"})

    def reset_node(self, node, data=None):
        node.remove_children()
        if data is not None:
            node.data = data

    def populate_dojo_modules(self, dojo_node, modules):
        dojo = dojo_node.data["dojo"]
        self.reset_node(dojo_node, {**dojo_node.data, "dojo": {**dojo, "modules": modules, "modules_loaded": True}, "loaded": True})
        for module in modules:
            module_node = dojo_node.add(
                display_name(module, "module"),
                {
                    "kind": "module",
                    "dojo": dojo,
                    "module": module,
                },
            )
            for challenge in module.get("challenges", []):
                module_node.add_leaf(
                    display_name(challenge, "challenge"),
                    {
                        "kind": "challenge",
                        "dojo": dojo,
                        "module": module,
                        "challenge": challenge,
                    },
                )

    def compose(self) -> ComposeResult:
        yield Header(show_clock=False)
        with Horizontal(id="body"):
            with Vertical(id="nav"):
                yield Static("Dojos", id="nav-title")
                yield VimTree("Challenge Browser", id="tree")
                yield Markdown("", id="start-pane")
            with Vertical(id="details-pane"):
                yield Static("Details", id="details-title")
                yield Markdown("Loading...", id="details")
        yield Static("", id="status")
        yield Footer()

    def on_mount(self):
        self.query_one("#start-pane", Markdown).display = False
        self.reload()
        self.query_one("#tree", Tree).focus()
        if self.start_error:
            self.sub_title = f"start failed: {self.start_error}"

    def select_tree_node(self, node):
        tree = self.query_one("#tree", Tree)
        tree.move_cursor(node)
        if node.data:
            self.update_selection(node.data)

    def show_browser_view(self):
        self.choosing_start = False
        self.query_one("#tree", Tree).display = True
        self.query_one("#start-pane", Markdown).display = False
        self.query_one("#nav", Vertical).remove_class("start-picker")
        self.query_one("#nav-title", Static).update("Dojos")
        self.query_one("#details-title", Static).update("Details")
        if self.selection:
            self.query_one("#details", Markdown).update(render_details(self.selection))

    def show_start_view(self):
        self.choosing_start = True
        dojo = self.selection["dojo"]
        module = self.selection["module"]
        challenge = self.selection["challenge"]
        description = (challenge.get("description") or "").strip() or "No description available."
        self.query_one("#tree", Tree).display = False
        self.query_one("#start-pane", Markdown).display = True
        self.query_one("#nav", Vertical).add_class("start-picker")
        self.query_one("#nav-title", Static).update("Start Challenge")
        self.query_one("#details-title", Static).update("Description")
        self.query_one("#start-pane", Markdown).update(
            "\n".join([
                f"# {display_name(challenge, 'challenge')}",
                "",
                f"- Dojo: `{display_name(dojo, 'dojo')}`",
                f"- Module: `{display_name(module, 'module')}`",
                f"- Challenge: `{challenge['id']}`",
                "",
                "Press `s` for standard mode.",
                "Press `p` for practice mode.",
                "Press `esc` to go back to the challenge picker.",
            ])
        )
        self.query_one("#details", Markdown).update(description)

    def reload(self):
        self.choosing_start = False
        self.show_browser_view()
        tree = self.query_one("#tree", Tree)
        details = self.query_one("#details", Markdown)
        status = self.query_one("#status", Static)
        status.update("Loading dojos...")
        details.update("Loading...")
        try:
            dojos = self.client.load_dojos()
        except Exception as error:
            tree.clear()
            details.update(f"# Failed to load catalog\n\n`{error}`")
            status.update("Load failed")
            return

        tree.clear()
        tree.root.label = "Challenge Browser"
        tree.root.data = {"kind": "root"}
        tree.root.expand()
        self.selection = None

        for dojo in dojos:
            dojo_node = tree.root.add(
                display_name(dojo, "dojo"),
                {"kind": "dojo", "dojo": dojo, "loaded": False},
                allow_expand=True,
            )
            dojo_node.collapse()
            self.add_loading_node(dojo_node)

        if tree.root.children:
            first = tree.root.children[0]
            self.call_after_refresh(lambda: self.select_tree_node(first))
            status.update("Use arrows to browse and enter to start")
            return

        details.update("# No dojos available")
        status.update("No dojos available")

    def update_selection(self, data):
        self.selection = data
        self.query_one("#details", Markdown).update(render_details(data))
        status = self.query_one("#status", Static)
        if data["kind"] == "challenge":
            status.update("Enter opens mode picker, s starts standard, p starts practice")
        elif data["kind"] == "module":
            status.update("Browse into the module to choose a challenge")
        elif data["kind"] == "dojo":
            status.update("Browse into the dojo to choose a module")
        else:
            status.update("Use arrows to browse")

    def on_tree_node_highlighted(self, event):
        if event.node.data:
            self.update_selection(event.node.data)

    def on_tree_node_selected(self, event):
        if not event.node.data:
            return
        self.update_selection(event.node.data)
        if event.node.data["kind"] == "challenge":
            self.open_start_modal()

    def on_tree_node_expanded(self, event):
        data = event.node.data
        if not data or data.get("loaded"):
            return

        status = self.query_one("#status", Static)
        details = self.query_one("#details", Markdown)

        try:
            if data["kind"] == "dojo":
                dojo = data["dojo"]
                status.update(f"Loading modules for {display_name(dojo, 'dojo')}...")
                modules = self.client.load_dojo_modules(dojo["id"])
                self.populate_dojo_modules(event.node, modules)
                if self.selection is data:
                    self.update_selection(event.node.data)
                status.update("Use arrows to browse and enter to start")
                return

        except Exception as error:
            self.reset_node(event.node)
            event.node.add_leaf(f"Load failed: {error}", {"kind": "error"})
            details.update(f"# Failed to load\n\n`{error}`")
            status.update("Load failed")

    def action_reload(self):
        self.reload()

    def action_cancel_start(self):
        if self.choosing_start:
            self.show_browser_view()
            if self.selection:
                self.update_selection(self.selection)
            self.query_one("#tree", Tree).focus()

    def action_start_standard(self):
        self.start_selected(False)

    def action_start_practice(self):
        self.start_selected(True)

    def open_start_modal(self):
        if not self.selection or self.selection["kind"] != "challenge":
            return
        self.show_start_view()
        self.query_one("#status", Static).update("Choose a mode: s starts standard, p starts practice")

    def start_selected(self, practice):
        if not self.selection or self.selection["kind"] != "challenge":
            return
        self.exit({
            "dojo": self.selection["dojo"]["id"],
            "module": self.selection["module"]["id"],
            "challenge": self.selection["challenge"]["id"],
            "practice": practice,
        })


def run_challenge_tui():
    client = ChallengeClient()
    start_error = None
    while True:
        selection = ChallengeBrowserApp(client, start_error=start_error).run()
        if not selection:
            return False
        print(f"Starting {selection['challenge']}...")
        try:
            client.start_challenge(selection["dojo"], selection["module"], selection["challenge"], selection["practice"])
            return True
        except Exception as error:
            start_error = str(error)
