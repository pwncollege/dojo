#!/usr/bin/env python3

import argparse
import os
import sys
import time

import requests
from itsdangerous.url_safe import URLSafeTimedSerializer
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.widgets import Footer, Header, Input, Markdown, Static


class OnboardingClient:
    def __init__(self, key_type, key_base64, fingerprint):
        self.key_type = key_type
        self.key_base64 = key_base64
        self.fingerprint = fingerprint
        self.ssh_key = os.environ.get("DOJO_SSH_SERVICE_KEY")
        if not self.ssh_key:
            raise RuntimeError("Missing DOJO_SSH_SERVICE_KEY")
        self.api_base = "http://pwn.college:80/pwncollege_api/v1"

    def headers(self):
        token = URLSafeTimedSerializer(self.ssh_key).dumps("ssh-onboarding")
        return {
            "Authorization": f"Bearer sk-ssh-service-{token}",
            "Content-Type": "application/json",
        }

    def payload(self, extra=None):
        payload = {
            "key_type": self.key_type,
            "key_base64": self.key_base64,
            "fingerprint": self.fingerprint,
        }
        if extra:
            payload.update(extra)
        return payload

    def post(self, path, payload):
        response = requests.post(f"{self.api_base}{path}", headers=self.headers(), json=payload, timeout=20)
        data = response.json()
        if not data.get("success"):
            errors = data.get("errors") or [data.get("error", "Request failed")]
            raise RuntimeError("\n".join(errors))
        return data

    def get(self, path):
        response = requests.get(f"{self.api_base}{path}", headers=self.headers(), timeout=20)
        data = response.json()
        if not data.get("success"):
            raise RuntimeError(data.get("error", "Request failed"))
        return data

    def register(self, name, email):
        return self.post("/ssh_onboarding/register", self.payload({"name": name, "email": email}))

    def create_link_request(self):
        return self.post("/ssh_onboarding/link_requests", self.payload())

    def link_status(self, token):
        return self.get(f"/ssh_onboarding/link_requests/{token}/status")


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

    Markdown {
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
        self.link_token = None

    def compose(self) -> ComposeResult:
        yield Header(show_clock=False)
        with Vertical(id="body"):
            yield Markdown("", id="content")
            yield Input("", id="input")
        yield Static("", id="status")
        yield Footer()

    def on_mount(self):
        self.show_menu()

    def content(self, text):
        self.query_one("#content", Markdown).update(text)

    def status(self, text):
        self.query_one("#status", Static).update(text)

    def input(self):
        return self.query_one("#input", Input)

    def set_input(self, placeholder="", value="", visible=False):
        input_widget = self.input()
        input_widget.placeholder = placeholder
        input_widget.value = value
        input_widget.display = visible
        if visible:
            input_widget.focus()

    def show_menu(self):
        self.state = "menu"
        self.link_token = None
        self.content(
            "\n".join([
                "# Set up SSH access",
                "",
                f"Key fingerprint: `{self.client.fingerprint or 'unknown'}`",
                "",
                "Press `c` to create a new pwn.college account.",
                "Press `l` to link this key to an existing account.",
                "Press `q` to quit.",
            ])
        )
        self.set_input("c=create, l=link, q=quit", visible=True)
        self.status("Choose create or link")

    def action_menu(self):
        self.show_menu()

    def action_create(self):
        if self.state != "menu":
            return
        self.state = "create-name"
        self.content("# Create account\n\nEnter the username you want to use on pwn.college.")
        self.set_input("username", visible=True)
        self.status("Enter username")

    def action_link(self):
        if self.state != "menu":
            return
        self.state = "link-starting"
        self.set_input()
        self.content("# Link existing account\n\nCreating a browser link...")
        self.status("Creating link")
        self.set_timer(0.1, self.create_link_request)

    def on_input_submitted(self, event):
        value = event.value.strip()
        if self.state == "menu":
            self.handle_menu_choice(value)
            return
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
            self.state = "create-submitting"
            self.set_input()
            self.content("# Creating account\n\nSubmitting registration...")
            self.status("Creating account")
            self.set_timer(0.1, lambda: self.finish_registration(self.account_name, value))

    def on_input_changed(self, event):
        if self.state == "menu" and event.value.strip().lower() in ("c", "l", "q"):
            self.handle_menu_choice(event.value)

    def handle_menu_choice(self, value):
        choice = value.strip().lower()
        self.input().value = ""
        if choice == "c":
            self.action_create()
        elif choice == "l":
            self.action_link()
        elif choice == "q":
            self.exit(False)
        else:
            self.status("Type c to create, l to link, or q to quit")

    def finish_registration(self, name, email):
        try:
            result = self.client.register(name, email)
        except Exception as error:
            self.state = "menu"
            self.content(
                "\n".join([
                    "# Account creation failed",
                    "",
                    f"```text\n{error}\n```",
                    "",
                    "Press `c` to try again or `l` to link an existing account.",
                ])
            )
            self.status("Registration failed")
            return
        user = result["user"]
        self.content(
            "\n".join([
                "# Account created",
                "",
                f"Created `{user['name']}` and linked this SSH key.",
                "",
                "Reconnect over SSH to start a challenge.",
            ])
        )
        self.status("Account created")
        self.set_timer(3, lambda: self.exit(True))

    def create_link_request(self):
        try:
            result = self.client.create_link_request()
        except Exception as error:
            self.state = "menu"
            self.content(
                "\n".join([
                    "# Link request failed",
                    "",
                    f"```text\n{error}\n```",
                    "",
                    "Press `l` to try again or `c` to create an account.",
                ])
            )
            self.status("Link request failed")
            return
        self.exit({"action": "link", "token": result["token"], "link_url": result["link_url"]})

    def poll_link_status(self):
        if self.state != "link-pending" or not self.link_token:
            return
        try:
            result = self.client.link_status(self.link_token)
        except Exception as error:
            self.content(f"# Link status failed\n\n```text\n{error}\n```")
            self.status("Status check failed")
            return
        if result["status"] == "pending":
            return
        if result["status"] == "linked":
            user = result.get("user") or {}
            self.content(
                "\n".join([
                    "# SSH key linked",
                    "",
                    f"Linked to `{user.get('name') or 'your account'}`.",
                    "",
                    "Reconnect over SSH to start a challenge.",
                ])
            )
            self.status("Linked")
            self.set_timer(3, lambda: self.exit(True))
            return
        self.content("# Link expired\n\nPress `l` to create a new link.")
        self.status("Link expired")
        self.state = "menu"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--key-type", required=True)
    parser.add_argument("--key-base64", required=True)
    parser.add_argument("--fingerprint", default="")
    args = parser.parse_args()
    client = OnboardingClient(args.key_type, args.key_base64, args.fingerprint)
    try:
        result = OnboardingApp(client).run()
    except Exception as error:
        print(f"Failed to start SSH onboarding: {error}", file=sys.stderr)
        return 1
    if isinstance(result, dict) and result.get("action") == "link":
        print()
        print("Open this link in your browser, log into pwn.college, and this SSH key will be added to your account:")
        print()
        print(result["link_url"])
        print()
        print("Waiting for the browser login to finish. Press Ctrl-C to stop waiting.")
        try:
            while True:
                status = client.link_status(result["token"])
                if status["status"] == "linked":
                    user = status.get("user") or {}
                    print(f"SSH key linked to {user.get('name') or 'your account'}. Reconnect over SSH to continue.")
                    break
                if status["status"] == "expired":
                    print("This link expired. Reconnect over SSH to create a new link.")
                    break
                time.sleep(2)
        except KeyboardInterrupt:
            print()
            print("Stopped waiting. The link remains valid until it expires.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
