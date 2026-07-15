#!/usr/bin/env python3

import argparse
import os
import pathlib
import sys

import requests
from itsdangerous.url_safe import URLSafeTimedSerializer
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.widgets import Footer, Header, Input, ListItem, ListView, Markdown, Static

from tui import run_challenge_tui


SSH_KEY_SETTINGS_URL = "https://pwn.college/settings#ssh-key"


class OnboardingClient:
    def __init__(self, key_type, key_base64):
        self.key_type = key_type
        self.key_base64 = key_base64
        self.ssh_key = os.environ.get("DOJO_SSH_SERVICE_KEY")
        if not self.ssh_key:
            raise RuntimeError("Missing DOJO_SSH_SERVICE_KEY")
        self.api_base = "http://pwn.college:80/pwncollege_api/v1"

    def register(self, name, email, password):
        token = URLSafeTimedSerializer(self.ssh_key).dumps("ssh-onboarding")
        response = requests.post(
            f"{self.api_base}/auth/register",
            headers={"Authorization": f"Bearer sk-ssh-service-{token}"},
            json={
                "key_type": self.key_type,
                "key_base64": self.key_base64,
                "name": name,
                "email": email,
                "password": password,
            },
            timeout=20,
        )
        data = response.json()
        if not data.get("success"):
            errors = data.get("errors") or [data.get("error", "Request failed")]
            raise RuntimeError("\n".join(errors))
        return data


class OnboardingApp(App):
    TITLE = "pwn.college"
    SUB_TITLE = "SSH setup"

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
        border: tall #78be20;
        background: #101010;
    }

    #heading {
        height: 3;
        content-align: center middle;
        color: #78be20;
        text-style: bold;
    }

    #instructions {
        height: 2;
        content-align: center middle;
        color: #00a3e0;
    }

    #choices {
        width: 1fr;
        height: 1fr;
        margin: 0 4;
        padding: 0 2;
        border: tall #78be20;
        background: #101010;
    }

    #choices > ListItem {
        height: 5;
        min-height: 5;
        margin: 0 1 1 1;
        padding: 0 3;
        color: #ffffff;
        background: #181818;
        border: tall #00a3e0;
    }

    #choices > ListItem.-highlight,
    #choices:focus > ListItem.-highlight {
        color: #000000;
        background: #ffc627;
        border: tall #ffc627;
        text-style: bold;
    }

    .choice-label {
        width: 1fr;
        height: 1fr;
        content-align: left middle;
    }

    #content {
        height: 1fr;
        padding: 0 1;
    }

    Input {
        margin: 0 1 1 1;
    }

    #status {
        height: 1;
        padding: 0 1;
        background: #272727;
        color: #00a3e0;
    }
    """

    BINDINGS = [
        Binding("c", "create", "Create"),
        Binding("l", "link", "Link"),
        Binding("q", "quit", "Quit"),
        Binding("escape", "menu", "Menu"),
    ]

    def __init__(self, client):
        super().__init__()
        self.client = client
        self.state = "menu"
        self.account_name = ""
        self.account_email = ""

    def compose(self) -> ComposeResult:
        yield Header(show_clock=False)
        with Vertical(id="body"):
            yield Static("Set up SSH access", id="heading")
            yield Static(
                "Press c to create an account or l to add an SSH key. Use ↑ / ↓ and Enter to choose.",
                id="instructions",
            )
            with ListView(id="choices"):
                with ListItem(id="create-account"):
                    yield Static(
                        "CREATE AN ACCOUNT\nChoose a username, email address, and password.",
                        classes="choice-label",
                    )
                with ListItem(id="link-key"):
                    yield Static(
                        "ADD AN SSH KEY TO AN EXISTING ACCOUNT\nOpen your pwn.college settings to add your public key.",
                        classes="choice-label",
                    )
            yield Markdown("", id="content")
            yield Input("", id="input")
        yield Static("", id="status")
        yield Footer()

    def on_mount(self):
        self.show_menu()

    def content(self, text):
        self.query_one("#content", Markdown).update(text)

    def heading(self, text):
        self.query_one("#heading", Static).update(text)

    def status(self, text):
        self.query_one("#status", Static).update(text)

    def input(self):
        return self.query_one("#input", Input)

    def set_input(self, placeholder="", value="", visible=False, password=False):
        input_widget = self.input()
        input_widget.placeholder = placeholder
        input_widget.value = value
        input_widget.password = password
        input_widget.display = visible
        if visible:
            input_widget.focus()

    def show_menu(self):
        self.state = "menu"
        self.heading("Set up SSH access")
        choices = self.query_one("#choices", ListView)
        choices.display = True
        choices.index = 0
        self.query_one("#content", Markdown).display = False
        self.set_input()
        choices.focus()
        self.status("Choose an option")

    def action_menu(self):
        if self.state in ("create-name", "create-email", "create-password"):
            self.show_menu()

    def action_create(self):
        if self.state != "menu":
            return
        self.state = "create-name"
        self.heading("Create a pwn.college account")
        self.query_one("#choices", ListView).display = False
        self.query_one("#content", Markdown).display = True
        self.content("# Create account\n\nEnter the username you want to use on pwn.college.")
        self.set_input("username", visible=True)
        self.status("Enter username")

    def action_link(self):
        if self.state != "menu":
            return
        self.exit({"action": "link"})

    def on_list_view_selected(self, event):
        if event.item.id == "create-account":
            self.action_create()
        elif event.item.id == "link-key":
            self.action_link()

    def on_input_submitted(self, event):
        value = event.value.strip()
        if self.state == "create-name":
            if not value:
                self.status("Username is required")
                return
            self.account_name = value
            self.state = "create-email"
            self.content("# Create account\n\nEnter your email address.")
            self.set_input("email", visible=True)
            self.status("Enter email")
            return
        if self.state == "create-email":
            if not value:
                self.status("Email is required")
                return
            self.account_email = value
            self.state = "create-password"
            self.content("# Create account\n\nEnter the password you want to use on pwn.college.")
            self.set_input("password", visible=True, password=True)
            self.status("Enter password")
            return
        if self.state == "create-password":
            if not value:
                self.status("Password is required")
                return
            self.state = "create-submitting"
            self.set_input()
            self.content("# Creating account\n\nSubmitting registration...")
            self.status("Creating account")
            self.set_timer(
                0.1,
                lambda: self.finish_registration(self.account_name, self.account_email, value),
            )

    def finish_registration(self, name, email, password):
        try:
            result = self.client.register(name, email, password)
        except Exception as error:
            self.show_menu()
            self.status(f"Account creation failed: {error}")
            return
        user = result["data"]
        self.content(
            "\n".join([
                "# Account created",
                "",
                f"Created `{user['username']}` and linked this SSH key.",
                "",
                "Opening the challenge browser...",
            ])
        )
        self.status("Account created")
        self.set_timer(2, lambda: self.exit({"action": "create", "user_id": user["user_id"]}))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--key-type", required=True)
    parser.add_argument("--key-base64", required=True)
    args = parser.parse_args()
    if os.environ.get("SSH_ORIGINAL_COMMAND"):
        print("This SSH key is not linked to a pwn.college account. Connect without a command to set it up.", file=sys.stderr)
        return 1
    client = OnboardingClient(args.key_type, args.key_base64)
    try:
        result = OnboardingApp(client).run()
    except Exception as error:
        print(f"Failed to start SSH onboarding: {error}", file=sys.stderr)
        return 1
    if isinstance(result, dict) and result.get("action") == "create":
        user_id = result["user_id"]
        try:
            if run_challenge_tui(user_id):
                enter_path = pathlib.Path(__file__).parent.resolve() / "enter.py"
                os.execv(sys.executable, [sys.executable, str(enter_path), f"user_{user_id}"])
        except Exception as error:
            print(f"Failed to launch challenge browser: {error}", file=sys.stderr)
            return 1
    if isinstance(result, dict) and result.get("action") == "link":
        print()
        print("Open your pwn.college settings and paste your SSH public key there:")
        print()
        print(SSH_KEY_SETTINGS_URL)
        print()
        print("After linking the key, reconnect over SSH to continue.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
