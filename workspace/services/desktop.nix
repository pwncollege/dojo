{ pkgs }:

let
  service = import ./service.nix { inherit pkgs; };
  fontsConf = pkgs.makeFontsConf {
    fontDirectories = [ pkgs.dejavu_fonts ];
  };
  xpraHtml5 = pkgs.xpra-html5.overrideAttrs (oldAttrs: rec {
    version = "20";
    src = pkgs.fetchFromGitHub {
      owner = "Xpra-org";
      repo = "xpra-html5";
      tag = "v${version}";
      hash = "sha256-sOHUqphOZ15FezQKe1r7DC3vYiwsI0I7IC8YiIv6m8E=";
    };
    postPatch = (oldAttrs.postPatch or "") + ''
      substituteInPlace html5/js/Window.js \
        --replace-fail \
          $'      if (this.override_redirect) {' \
          $'      if (this.client.server_is_desktop || this.client.server_is_shadow || this.override_redirect) {'
      substituteInPlace html5/js/Window.js \
        --replace-fail \
          $'      if (this.client.session_name) {\n        jQuery("title").text(client.session_name);\n      }\n      else {' \
          $'      if (this.client.workspace_route_password) {\n        jQuery("title").text("Desktop");\n      }\n      else if (this.client.session_name) {\n        jQuery("title").text(client.session_name);\n      }\n      else {'
      substituteInPlace html5/css/client.css \
        --replace-fail \
          $'div.window canvas {' \
          $'div.window canvas,\ndiv.undecorated canvas {'
      substituteInPlace html5/index.html \
        --replace-fail \
          '$("div.window canvas")' \
          '$("div.window canvas, div.undecorated canvas")'
      substituteInPlace html5/index.html \
        --replace-fail \
          $'  <head>' \
          $'  <head>\n    <meta name="referrer" content="no-referrer">'
      substituteInPlace html5/index.html \
        --replace-fail \
          $'        const username = getparam("username") || getparam("handle") || null;\n        const passwords = [];\n        for (let i = 0; i < 10; i++) {\n          let password = getparam("password" + i) || getparam("token" + i) || null;\n          if (!password && i == 0) {\n            //try with no suffix:\n            password = getparam("password") || getparam("token") || null;\n          }\n          if (password) {\n            passwords.push(password);\n          } else {\n            break;\n          }\n        }' \
          $'        const workspace_route = window.location.pathname.match(\n          new RegExp("^/workspace/[^/]+/([A-Za-z0-9_-]{43}=)/xpra/(6080|6081)(?:/|$)")\n        );\n        const username = getparam("username") || getparam("handle") || null;\n        const passwords = [];\n        if (workspace_route) {\n          passwords.push(workspace_route[1]);\n        } else {\n          for (let i = 0; i < 10; i++) {\n            let password = getparam("password" + i) || getparam("token" + i) || null;\n            if (!password && i == 0) {\n              password = getparam("password") || getparam("token") || null;\n            }\n            if (password) {\n              passwords.push(password);\n            } else {\n              break;\n            }\n          }\n        }'
      substituteInPlace html5/index.html \
        --replace-fail \
          $'        const path = getstrparam("path", ALLOWED_CHARS + "/") || window.location.pathname;' \
          $'        const path = workspace_route\n          ? window.location.pathname\n          : getstrparam("path", ALLOWED_CHARS + "/") || window.location.pathname;'
      substituteInPlace html5/index.html \
        --replace-fail \
          $'        try {\n          Utilities.setSessionStorageValue("password", null);\n        } catch (e) {\n          //ignore\n        }\n        try {\n          Utilities.setSessionStorageValue("token", null);\n        } catch (e) {\n          //ignore\n        }' \
          $'        if (!workspace_route) {\n          try {\n            Utilities.setSessionStorageValue("password", null);\n          } catch (e) {\n          }\n          try {\n            Utilities.setSessionStorageValue("token", null);\n          } catch (e) {\n          }\n        }'
      substituteInPlace html5/index.html \
        --replace-fail \
          $'        const server = getstrparam("server") || window.location.hostname;' \
          $'        const server = workspace_route ? window.location.hostname : getstrparam("server") || window.location.hostname;' \
        --replace-fail \
          $'        const port = getintparam("port") || window.location.port;' \
          $'        const port = workspace_route ? window.location.port : getintparam("port") || window.location.port;' \
        --replace-fail \
          $'        const ssl = getboolparam("ssl", https);' \
          $'        const ssl = workspace_route ? https : getboolparam("ssl", https);' \
        --replace-fail \
          $'        const webtransport = getboolparam("webtransport", false);' \
          $'        const webtransport = workspace_route ? false : getboolparam("webtransport", false);' \
        --replace-fail \
          $'        const encryption = getstrparam("encryption") || "";' \
          $'        const encryption = workspace_route ? "" : getstrparam("encryption") || "";' \
        --replace-fail \
          $'        const key = getstrparam("key") || null;' \
          $'        const key = workspace_route ? null : getstrparam("key") || null;' \
        --replace-fail \
          $'        const insecure = getboolparam("insecure", false);' \
          $'        const insecure = workspace_route ? false : getboolparam("insecure", false);'
      substituteInPlace html5/index.html \
        --replace-fail \
          $'        if (passwords) {\n          client.passwords = passwords;\n        }' \
          $'        if (passwords) {\n          client.passwords = passwords;\n        }\n        client.workspace_route_password = workspace_route ? workspace_route[1] : null;'
      substituteInPlace html5/index.html \
        --replace-fail \
          $'            const has_session_storage = Utilities.hasSessionStorage();' \
          $'            const has_session_storage = !workspace_route && Utilities.hasSessionStorage();' \
        --replace-fail \
          $'            if (insecure || Utilities.hasSessionStorage()) {\n              for (let i = 0; i < passwords.length; i++) {\n                add_prop("password" + i, passwords[i]);\n              }\n            } else {\n              props["password"] = "";\n            }' \
          $'            if (!workspace_route && (insecure || Utilities.hasSessionStorage())) {\n              for (let i = 0; i < passwords.length; i++) {\n                add_prop("password" + i, passwords[i]);\n              }\n            } else if (!workspace_route) {\n              props["password"] = "";\n            }'
      substituteInPlace html5/index.html \
        --replace-fail \
          $'            clog("closing: ", reason);\n            if (!submit) {' \
          $'            clog("closing: ", reason);\n            if (workspace_route) {\n              connection_progress("Connection closed", reason || "socket closed", 0);\n              return;\n            }\n            if (!submit) {'
      substituteInPlace html5/js/Client.js \
        --replace-fail \
          $'      "argv": [window.location.href],' \
          $'      "argv": [],' \
        --replace-fail \
          $'    this.session_name = hello["session_name"];\n    $("title").text(this.session_name);' \
          $'    this.session_name = hello["session_name"];\n    $("title").text(this.workspace_route_password ? "Desktop" : this.session_name);' \
        --replace-fail \
          $'        this.session_name = value;\n        jQuery("title").text(value);' \
          $'        this.session_name = value;\n        jQuery("title").text(this.workspace_route_password ? "Desktop" : value);' \
        --replace-fail \
          $'    let details = `''${this.host}:''${this.port}''${this.path}`;\n    if (this.ssl) {\n      details += " with ssl";\n    }' \
          $'    let details = this.workspace_route_password ? "workspace route" : `''${this.host}:''${this.port}''${this.path}`;\n    if (this.ssl && !this.workspace_route_password) {\n      details += " with ssl";\n    }' \
        --replace-fail \
          $'    this.uri = uri;\n    this.on_connection_progress("Opening WebSocket connection", uri, 50);\n    this.protocol.open(uri);' \
          $'    const connection_uri = this.workspace_route_password ? "workspace route" : uri;\n    this.uri = connection_uri;\n    this.on_connection_progress("Opening WebSocket connection", connection_uri, 50);\n    this.protocol.open(uri);' \
        --replace-fail \
          $'  _get_digests() {\n    const digests = ["xor", "keycloak", "hmac+sha256"];' \
          $'  _get_digests() {\n    if (this.workspace_route_password) {\n      return ["hmac+sha256"];\n    }\n    const digests = ["xor", "keycloak", "hmac+sha256"];' \
        --replace-fail \
          $'    const salt_digest = packet[4] || "xor";\n    const prompt = (packet[5] || "password").replace(/[^\\d+,. /:a-z]/gi, "");' \
          $'    const salt_digest = packet[4] || "xor";\n    if (this.workspace_route_password && (digest !== "hmac+sha256" || salt_digest !== "hmac+sha256")) {\n      this.disconnect("workspace routes require hmac+sha256 authentication");\n      return;\n    }\n    const prompt = (packet[5] || "password").replace(/[^\\d+,. /:a-z]/gi, "");' \
        --replace-fail \
          $'      const password = this.passwords.shift();' \
          $'      const password = this.workspace_route_password || this.passwords.shift();' \
        --replace-fail \
          $'      Utilities.clog("call_do_process_challenge(", password, ")");' \
          ""
    '';
  });
  xpra = (pkgs.xpra.override { xpra-html5 = xpraHtml5; }).overrideAttrs (oldAttrs: {
    postPatch = (oldAttrs.postPatch or "") + ''
      substituteInPlace xpra/server/base.py \
        --replace-fail \
          $'    def _request_exit(self, reason: ConnectionMessage | str = "") -> None:\n        message = "Exiting in response to client request"' \
          $'    def _request_exit(self, reason: ConnectionMessage | str = "") -> None:\n        if not self.client_shutdown:\n            log.warn("Warning: ignoring exit request")\n            return\n        message = "Exiting in response to client request"'
      substituteInPlace xpra/x11/subsystem/icc.py \
        --replace-fail \
          $'    def reset_icc_profile(self) -> None:\n        log("reset_icc_profile()")' \
          $'    def reset_icc_profile(self) -> None:\n        if not SYNC_ICC:\n            return\n        log("reset_icc_profile()")'
      substituteInPlace xpra/x11/selection/proxy.py \
        --replace-fail \
          $'    def claim(self) -> None:\n        time = 0' \
          $'    def claim(self) -> None:\n        if not self._can_receive:\n            return\n        time = 0'
      substituteInPlace xpra/server/subsystem/keyboard.py \
        --replace-fail \
          $'    def parse_hello_ui_keyboard(self, ss, c: typedict) -> None:\n        other_ui_clients:' \
          $'    def parse_hello_ui_keyboard(self, ss, c: typedict) -> None:\n        if self.readonly:\n            return\n        other_ui_clients:'
      substituteInPlace xpra/x11/subsystem/display.py \
        --replace-fail \
          $'    def _process_force_ungrab(self, proto, _packet: Packet) -> None:\n        # ignore the window id: wid = packet[1]' \
          $'    def _process_force_ungrab(self, proto, _packet: Packet) -> None:\n        if self.readonly:\n            return\n        # ignore the window id: wid = packet[1]'
      substituteInPlace xpra/auth/file.py \
        --replace-fail \
          'from xpra.net.digest import verify_digest' \
          $'from collections.abc import Sequence\n\nfrom xpra.net.digest import verify_digest' \
        --replace-fail \
          $'class Authenticator(FileAuthenticatorBase):\n\n    def authenticate_hmac' \
          $'class Authenticator(FileAuthenticatorBase):\n\n    def get_challenge(self, digests: Sequence[str]) -> tuple[bytes, str]:\n        if "hmac+sha256" not in digests:\n            raise ValueError("file authentication requires hmac+sha256")\n        return super().get_challenge(("hmac+sha256",))\n\n    def choose_salt_digest(self, digest_modes: Sequence[str]) -> str:\n        return super().choose_salt_digest(("hmac+sha256",))\n\n    def authenticate_hmac'
    '';
  });
  xpraXorgConf = pkgs.runCommand "xpra-xorg.conf" { } ''
    ${pkgs.gnused}/bin/sed \
      -e 's/VideoRam 768000/VideoRam 65536/' \
      -e 's/Virtual 11520 6318/Virtual 4096 2160/g' \
      ${xpra}/etc/xpra/xorg.conf > $out
  '';
  serviceReadiness = ''
    wait_for_service() {
      local pid_file="$1"
      shift
      local service_pid=
      local candidate=
      local deadline=$((SECONDS + 75))

      while (( SECONDS < deadline )); do
        if [ -z "$service_pid" ] && [ -r "$pid_file" ]; then
          read -r candidate < "$pid_file"
          if kill -0 "$candidate" 2>/dev/null; then
            service_pid="$candidate"
          fi
        fi
        if [ -n "$service_pid" ]; then
          if ! kill -0 "$service_pid" 2>/dev/null; then
            printf 'Service exited before becoming ready: %s\n' "$pid_file" >&2
            return 1
          fi
          if "$@" && kill -0 "$service_pid" 2>/dev/null; then
            return 0
          fi
        fi
        sleep 0.1
      done

      printf 'Service readiness timed out: %s\n' "$pid_file" >&2
      return 1
    }
  '';
  serviceLifecycle = ''
    managed_service_running() {
      local pid_file="/run/dojo/var/$1.pid"
      local service_pid=

      [ -r "$pid_file" ] || return 1
      read -r service_pid < "$pid_file"
      kill -0 "$service_pid" 2>/dev/null
    }

    terminate_managed_service() {
      local service_name="$1"
      local pid_file="/run/dojo/var/$service_name.pid"
      local service_pid=
      local service_pgid=
      local deadline=

      if [ -r "$pid_file" ]; then
        read -r service_pid < "$pid_file"
      fi
      if [ -n "$service_pid" ] && kill -0 "$service_pid" 2>/dev/null; then
        service_pgid="$(${pkgs.procps}/bin/ps -o pgid= -p "$service_pid" | ${pkgs.coreutils}/bin/tr -d ' ')"
        if [ -n "$service_pgid" ] && [ "$service_pgid" -gt 1 ]; then
          kill -TERM -- "-$service_pgid" 2>/dev/null || true
        else
          kill -TERM "$service_pid" 2>/dev/null || true
        fi
        deadline=$((SECONDS + 5))
        while kill -0 "$service_pid" 2>/dev/null && (( SECONDS < deadline )); do
          sleep 0.1
        done
        if kill -0 "$service_pid" 2>/dev/null; then
          if [ -n "$service_pgid" ] && [ "$service_pgid" -gt 1 ]; then
            kill -KILL -- "-$service_pgid" 2>/dev/null || true
          else
            kill -KILL "$service_pid" 2>/dev/null || true
          fi
        fi
      fi
      rm -f "$pid_file"
    }

    terminate_recorded_xorg() {
      local xvfb_pid_file=
      local xvfb_pid=
      local xvfb_executable=
      local deadline=

      for xvfb_pid_file in /run/dojo/var/desktop-service/sessions/*/xvfb.pid; do
        [ -r "$xvfb_pid_file" ] || continue
        read -r xvfb_pid < "$xvfb_pid_file"
        if [ -n "$xvfb_pid" ] && kill -0 "$xvfb_pid" 2>/dev/null; then
          xvfb_executable="$(${pkgs.coreutils}/bin/readlink -f "/proc/$xvfb_pid/exe" 2>/dev/null || true)"
          if [ "$xvfb_executable" = "${pkgs.xorg-server}/bin/Xorg" ]; then
            kill -TERM "$xvfb_pid" 2>/dev/null || true
            deadline=$((SECONDS + 5))
            while kill -0 "$xvfb_pid" 2>/dev/null && (( SECONDS < deadline )); do
              sleep 0.1
            done
            if kill -0 "$xvfb_pid" 2>/dev/null; then
              kill -KILL "$xvfb_pid" 2>/dev/null || true
            fi
          fi
        fi
        rm -f "$xvfb_pid_file"
      done
    }
  '';
  xfdesktop = pkgs.xfdesktop.overrideAttrs (oldAttrs: {
    postPatch = (oldAttrs.postPatch or "") + ''
      substituteInPlace src/xfdesktop-file-icon-manager.c \
        --replace-fail \
          $'    if (mdata->position_config == NULL) {\n        g_assert(candidates != NULL);' \
          $'    if (mdata->position_config == NULL && candidates != NULL) {\n        mdata->position_config = candidates->data;\n        xfdesktop_icon_position_configs_assign_monitor(fmanager->position_configs, mdata->position_config, monitor);\n        g_clear_pointer(&candidates, g_list_free);\n    }\n\n    if (mdata->position_config == NULL) {\n        g_assert(candidates != NULL);'
    '';
  });

  desktopStartScript = pkgs.writeScript "dojo-desktop-start" ''
    #!${pkgs.bash}/bin/bash

    ${serviceReadiness}
    ${serviceLifecycle}

    until [ -f /run/dojo/var/ready ]; do sleep 0.1; done

    export DISPLAY=:0
    export XDG_DATA_DIRS="/run/dojo/share:''${XDG_DATA_DIRS:-/usr/local/share:/usr/share}"
    export XDG_CONFIG_DIRS="/run/dojo/etc/xdg:''${XDG_CONFIG_DIRS:-/etc/xdg}"
    export FONTCONFIG_FILE="${fontsConf}"
    export XDG_RUNTIME_DIR=/run/dojo/var/desktop-service/runtime
    export XPRA_CLIENT_CAN_SHUTDOWN=0
    export PATH="${pkgs.xauth}/bin:${pkgs.xorg-server}/bin:$PATH"

    mkdir -p "$XDG_RUNTIME_DIR" /run/dojo/var/desktop-service/sessions /run/dojo/var/desktop-service/sockets /run/dojo/var/desktop-tls
    chmod 700 "$XDG_RUNTIME_DIR" /run/dojo/var/desktop-service/sessions /run/dojo/var/desktop-service/sockets /run/dojo/var/desktop-tls

    if [ -z "''${DOJO_XPRA_DESKTOP_ROUTE_PASSWORD:-}" ]; then
      printf 'Missing desktop workspace route password\n' >&2
      exit 1
    fi
    if [ -z "''${DOJO_XPRA_TLS_CERTIFICATE:-}" ] || [ -z "''${DOJO_XPRA_TLS_PRIVATE_KEY:-}" ]; then
      printf 'Missing desktop transport credentials\n' >&2
      exit 1
    fi
    umask 077
    desktop_route_password=$(mktemp /run/dojo/var/desktop-service/xpra-route-password.XXXXXX)
    printf '%s' "$DOJO_XPRA_DESKTOP_ROUTE_PASSWORD" > "$desktop_route_password"
    tls_certificate=$(mktemp /run/dojo/var/desktop-tls/certificate.XXXXXX)
    tls_private_key=$(mktemp /run/dojo/var/desktop-tls/private-key.XXXXXX)
    printf '%s' "$DOJO_XPRA_TLS_CERTIFICATE" > "$tls_certificate"
    printf '%s' "$DOJO_XPRA_TLS_PRIVATE_KEY" > "$tls_private_key"

    desktop_restart=0
    if managed_service_running desktop-service/xpra && {
      [ ! -r /run/dojo/var/desktop-service/xpra-route-password ] ||
      [ ! -r /run/dojo/var/desktop-tls/certificate.pem ] ||
      [ ! -r /run/dojo/var/desktop-tls/private-key.pem ] ||
      ! ${pkgs.diffutils}/bin/cmp -s "$desktop_route_password" /run/dojo/var/desktop-service/xpra-route-password ||
      ! ${pkgs.diffutils}/bin/cmp -s "$tls_certificate" /run/dojo/var/desktop-tls/certificate.pem ||
      ! ${pkgs.diffutils}/bin/cmp -s "$tls_private_key" /run/dojo/var/desktop-tls/private-key.pem
    }; then
      desktop_restart=1
    fi
    if [ -e /run/dojo/var/desktop-service/Xvnc.pid ] ||
       [ -e /run/dojo/var/desktop-service/novnc.pid ] ||
       [ -e /run/dojo/var/desktop-service/Xvnc.sock ] ||
       [ -e /run/dojo/var/desktop-service/Xvnc.passwd ]; then
      desktop_restart=1
    fi
    if ! managed_service_running desktop-service/xpra; then
      for xvfb_pid_file in /run/dojo/var/desktop-service/sessions/*/xvfb.pid; do
        if [ -e "$xvfb_pid_file" ]; then
          desktop_restart=1
          break
        fi
      done
    fi
    if [ "$desktop_restart" -eq 1 ]; then
      terminate_managed_service desktop-view-service/xpra
      terminate_managed_service desktop-service/xfce4-session
      terminate_managed_service desktop-service/novnc
      terminate_managed_service desktop-service/xpra
      terminate_recorded_xorg
      terminate_managed_service desktop-service/Xvnc
      rm -f /run/dojo/var/desktop-service/Xvnc.sock /run/dojo/var/desktop-service/Xvnc.passwd
      rm -f /tmp/.X11-unix/X0 /tmp/.X0-lock
      rm -rf /run/dojo/var/desktop-service/sessions/* /run/dojo/var/desktop-service/sockets/*
      rm -rf /run/dojo/var/desktop-view-service/sessions/* /run/dojo/var/desktop-view-service/sockets/*
    fi

    mv -f "$desktop_route_password" /run/dojo/var/desktop-service/xpra-route-password
    mv -f "$tls_certificate" /run/dojo/var/desktop-tls/certificate.pem
    mv -f "$tls_private_key" /run/dojo/var/desktop-tls/private-key.pem
    unset DOJO_XPRA_DESKTOP_ROUTE_PASSWORD
    unset DOJO_XPRA_TLS_CERTIFICATE
    unset DOJO_XPRA_TLS_PRIVATE_KEY

    ${service}/bin/dojo-service start desktop-service/xpra \
      ${pkgs.coreutils}/bin/env -u DOJO_AUTH_TOKEN XPRA_UNAUTHENTICATED_HELLO_REQUESTS= ${xpra}/bin/xpra monitor $DISPLAY \
        --daemon=no \
        --attach=no \
        --use-display=no \
        --bind=none \
        --bind-wss=0.0.0.0:6080,auth=file,filename=/run/dojo/var/desktop-service/xpra-route-password,verify-username=no,info=no,exit=no,stop=no,detach=no \
        --ssl-cert=/run/dojo/var/desktop-tls/certificate.pem \
        --ssl-key=/run/dojo/var/desktop-tls/private-key.pem \
        --html=${xpraHtml5}/share/xpra/www \
        --http-scripts=off \
        --ssl-upgrade=no \
        --rfb-upgrade=no \
        --mmap=no \
        --source=no \
        --resize-display=yes:1024x768 \
        --pixel-depth=24 \
        --input-devices=xtest \
        --xvfb='${pkgs.xorg-server}/bin/Xorg -novtswitch -logfile $XPRA_SESSION_DIR/Xorg.log -config ${xpraXorgConf} +extension Composite +extension RANDR +extension RENDER -extension DOUBLE-BUFFER -extension GLX -nolisten tcp -noreset -auth $XAUTHORITY' \
        --sessions-dir=/run/dojo/var/desktop-service/sessions \
        --socket-dir=/run/dojo/var/desktop-service/sockets \
        --commands=no \
        --shell=no \
        --control=no \
        --dbus=no \
        --pulseaudio=no \
        --audio=no \
        --webcam=no \
        --printing=no \
        --file-transfer=no \
        --open-files=no \
        --open-url=no \
        --start-new-commands=no \
        --notifications=no \
        --tray=no \
        --system-tray=no \
        --bell=no \
        --mdns=no \
        --sharing=yes \
        --lock=no \
        --remote-logging=no \
        --opengl=no \
        --clipboard-direction=both

    wait_for_service /run/dojo/var/desktop-service/xpra.pid test -e /tmp/.X11-unix/X0 || exit 1
    wait_for_service /run/dojo/var/desktop-service/xpra.pid ${pkgs.curl}/bin/curl -kfs -o /dev/null https://localhost:6080/ || exit 1

    # By default, xfce4-session invokes dbus-launch without `--config-file`, and it fails to find /etc/dbus-1/session.conf; so we manually specify the config file here.
    ${service}/bin/dojo-service start desktop-service/xfce4-session \
      ${pkgs.dbus}/bin/dbus-launch --sh-syntax --exit-with-session --config-file=${pkgs.dbus}/share/dbus-1/session.conf ${pkgs.xfce4-session}/bin/xfce4-session
  '';

  desktopViewStartScript = pkgs.writeScript "dojo-desktop-view-start" ''
    #!${pkgs.bash}/bin/bash

    ${serviceReadiness}
    ${serviceLifecycle}

    if [ -z "''${DOJO_XPRA_VIEW_ROUTE_PASSWORD:-}" ]; then
      printf 'Missing view-only desktop workspace route password\n' >&2
      exit 1
    fi
    mkdir -p /run/dojo/var/desktop-view-service
    umask 077
    view_route_password=$(mktemp /run/dojo/var/desktop-view-service/xpra-route-password.XXXXXX)
    printf '%s' "$DOJO_XPRA_VIEW_ROUTE_PASSWORD" > "$view_route_password"
    if managed_service_running desktop-view-service/xpra && {
      [ ! -r /run/dojo/var/desktop-view-service/xpra-route-password ] ||
      ! ${pkgs.diffutils}/bin/cmp -s "$view_route_password" /run/dojo/var/desktop-view-service/xpra-route-password
    }; then
      terminate_managed_service desktop-view-service/xpra
      rm -rf /run/dojo/var/desktop-view-service/sessions/* /run/dojo/var/desktop-view-service/sockets/*
    fi
    mv -f "$view_route_password" /run/dojo/var/desktop-view-service/xpra-route-password
    unset DOJO_XPRA_VIEW_ROUTE_PASSWORD

    ${desktopStartScript}
    unset DOJO_XPRA_DESKTOP_ROUTE_PASSWORD
    unset DOJO_XPRA_TLS_CERTIFICATE
    unset DOJO_XPRA_TLS_PRIVATE_KEY

    export DISPLAY=:0
    export XDG_DATA_DIRS="/run/dojo/share:''${XDG_DATA_DIRS:-/usr/local/share:/usr/share}"
    export XDG_CONFIG_DIRS="/run/dojo/etc/xdg:''${XDG_CONFIG_DIRS:-/etc/xdg}"
    export FONTCONFIG_FILE="${fontsConf}"
    export XDG_RUNTIME_DIR=/run/dojo/var/desktop-view-service/runtime
    export XPRA_CLIENT_CAN_SHUTDOWN=0
    export XPRA_SYNC_ICC=0
    export PATH="${pkgs.xauth}/bin:${pkgs.xorg-server}/bin:$PATH"

    mkdir -p "$XDG_RUNTIME_DIR" /run/dojo/var/desktop-view-service/sessions /run/dojo/var/desktop-view-service/sockets
    chmod 700 "$XDG_RUNTIME_DIR" /run/dojo/var/desktop-view-service/sessions /run/dojo/var/desktop-view-service/sockets

    wait_for_service /run/dojo/var/desktop-service/xpra.pid test -e /tmp/.X11-unix/X0 || exit 1

    ${service}/bin/dojo-service start desktop-view-service/xpra \
      ${pkgs.coreutils}/bin/env -u DOJO_AUTH_TOKEN XPRA_UNAUTHENTICATED_HELLO_REQUESTS= ${xpra}/bin/xpra shadow $DISPLAY \
        --daemon=no \
        --attach=no \
        --use-display=yes \
        --bind=none \
        --bind-wss=0.0.0.0:6081,auth=file,filename=/run/dojo/var/desktop-view-service/xpra-route-password,verify-username=no,info=no,exit=no,stop=no,detach=no \
        --ssl-cert=/run/dojo/var/desktop-tls/certificate.pem \
        --ssl-key=/run/dojo/var/desktop-tls/private-key.pem \
        --html=${xpraHtml5}/share/xpra/www \
        --http-scripts=off \
        --ssl-upgrade=no \
        --rfb-upgrade=no \
        --mmap=no \
        --source=no \
        --readonly=yes \
        --resize-display=no \
        --sessions-dir=/run/dojo/var/desktop-view-service/sessions \
        --socket-dir=/run/dojo/var/desktop-view-service/sockets \
        --commands=no \
        --shell=no \
        --control=no \
        --dbus=no \
        --pulseaudio=no \
        --audio=no \
        --webcam=no \
        --printing=no \
        --file-transfer=no \
        --open-files=no \
        --open-url=no \
        --start-new-commands=no \
        --notifications=no \
        --tray=no \
        --system-tray=no \
        --bell=no \
        --mdns=no \
        --sharing=yes \
        --lock=no \
        --remote-logging=no \
        --opengl=no \
        --clipboard-direction=to-client

    wait_for_service /run/dojo/var/desktop-view-service/xpra.pid ${pkgs.curl}/bin/curl -kfs -o /dev/null https://localhost:6081/ || exit 1
  '';

  serviceScript = pkgs.writeScript "dojo-desktop" ''
    #!${pkgs.bash}/bin/bash

    mkdir -p /run/dojo/var
    exec ${pkgs.util-linux}/bin/flock --close --exclusive /run/dojo/var/desktop-start.lock ${desktopStartScript}
  '';

  viewServiceScript = pkgs.writeScript "dojo-desktop-view" ''
    #!${pkgs.bash}/bin/bash

    mkdir -p /run/dojo/var
    exec ${pkgs.util-linux}/bin/flock --close --exclusive /run/dojo/var/desktop-start.lock ${desktopViewStartScript}
  '';

  xfce = pkgs.symlinkJoin {
    name = "xfce";
    paths = with pkgs; [
      xfce4-session
      xfce4-settings
      xfce4-terminal
      xfce4-panel
      xfce4-appfinder
      xfwm4
      xfdesktop
      xfconf
      xfce4-exo
      thunar
      dbus
      dconf
      xclip
      dejavu_fonts
      blackbird
    ];
  };

in
pkgs.stdenv.mkDerivation {
  name = "desktop-service";
  src = ./desktop;

  buildInputs = with pkgs; [
    bash
    curl
    rsync
  ];
  propagatedBuildInputs = with pkgs; [
    xpra
    xfce
    elementary-xfce-icon-theme # If we include this in `xfce`, we get a "Permission denied" error related to `nix-support/propagated-build-inputs`.
  ];

  dontRewriteSymlinks = true;
  dontMoveSystemdUserUnits = true; # We run into an issue where we `mv` "the same file".

  unpackPhase = ''
    runHook preUnpack
    cp -r $src $PWD
    runHook postUnpack
  '';

  installPhase = ''
    runHook preInstall
    mkdir -p $out/bin
    cp ${serviceScript} $out/bin/dojo-desktop
    cp ${viewServiceScript} $out/bin/dojo-desktop-view
    ln -s ${xpra}/bin/xpra $out/bin/xpra
    ln -s ${pkgs.xfce4-terminal}/bin/xfce4-terminal $out/bin/x-terminal-emulator
    rsync -a --ignore-existing $src/. ${xfce}/. ${pkgs.elementary-xfce-icon-theme}/. $out
    runHook postInstall
  '';
}
