# Desktop clipboard integration checks

These are opt-in real-browser checks, not part of the normal Dojo test suite.
They use separate browser and remote X displays, OS clipboards through xclip,
and real keyboard/mouse input through Selenium. Clipboard APIs are not mocked.
The GUI fixture records actual inserted text and has an explicit Ctrl+Shift+V
binding to exercise the terminal-style paste chord; this is not a test of XFCE
Terminal itself.

## Environment used

Isolated Ubuntu 24.04 container, without host mounts or published ports:

- Firefox 155.0.1 at `/opt/test/firefox/firefox`; geckodriver 0.36 at `/opt/test/geckodriver`.
- Google Chrome 153.0.8010.36 at `/usr/bin/google-chrome`; matching driver at `/opt/test/chromedriver-linux64/chromedriver`.
- Python 3, Selenium 4.18.1, tkinter, xclip, Xvfb, openbox, TigerVNC 1.13.1, websockify.
- Browser Xvfb `:99`, 1280x960x24, with openbox. Remote TigerVNC `:101`, 1024x768.
- Built noVNC assets in `/opt/test/novnc-modern`, served by websockify on **127.0.0.1:6083**, forwarding to **127.0.0.1:5901**.
- Parent HTTP server on **127.0.0.1:8090**, serving `/opt/test`. `novnc-embedded.html` embeds the cross-origin viewer with Dojo's clipboard allow attributes.

Copy this directory's files into `/opt/test` and create `/opt/test/results`.
Start the X displays, window manager, VNC server, and HTTP servers in that isolated
environment. The remote test VNC server used `-localhost yes -SecurityTypes None`;
do not expose it outside the test container. Then run:

```sh
DISPLAY=:101 python3 /opt/test/clipboard_app.py
```

In another terminal:

```sh
python3 /opt/test/fallback_probe.py
```

The probe runs Firefox, granted Chrome, and fresh/ungranted Chrome sequentially.
For a single variant, set `ONLY=firefoxFalse`, `ONLY=chromeTrue`, or
`ONLY=chromeFalse`. Do not run another interactive browser on display :99 during
these tests: clipboard permissions and focus are part of what is being tested.

Check every `checks.*.pass` field and absence of `error` in the output JSON files;
the script writes diagnostics even after failures. Chrome's granted variant uses
CDP permissions for parent and child origins, not a person accepting a prompt.

## Cases

- Real Ctrl+V and Ctrl+Shift+V transfer Unicode/multiline text and insert it into
  the remote GUI, with stale remote clipboard data preloaded.
- Canvas focus restoration and typing after paste (no stuck modifiers).
- Remote application select-all/copy reaches the browser OS clipboard.
- Remote update after seven seconds idle: automatic with Chrome grants, or a
  subsequent desktop click with Firefox/fresh Chrome.
- Pending remote writes do not overwrite fresh local paste contents.
- Leaving/re-entering the desktop cancels stale pending writes; granted Chrome
  still reads the new local clipboard on focus.
- Manual panel remains available.
- View-only blocks both directions; switching back restores paste capture.

## Scope and limitations

The test uses a localhost secure context and Dojo-like iframe permissions, not
the full Dojo TLS/authentication/proxy deployment. It tests text, not images or
rich clipboard data. It does not establish Safari, Edge, mobile callout-menu,
IME, remote application menu paste, or WAN behavior. Safari's standards support
makes gesture-based clipboard plausible, but real macOS testing is required.

The patch deliberately keeps the manual panel, only reads automatically with a
pre-existing Chromium permission grant, and avoids idle Chromium write prompts.
A queued remote copy can be written on a later desktop click; privacy controls
and user messaging deserve further review before default rollout.

For upstream context and reconnect-patch history, see
[CLIPBOARD-LANDSCAPE.md](CLIPBOARD-LANDSCAPE.md).
