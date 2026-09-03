{ pkgs }:

let
  service = import ./service.nix { inherit pkgs; };
  fontsConf = pkgs.makeFontsConf {
    fontDirectories = [ pkgs.dejavu_fonts ];
  };
  xpraHtml5Settings = pkgs.writeText "xpra-html5-default-settings" ''
    reconnect = true
    clipboard = true
    sharing = true
    steal = true
    toolbar_position = novnc
    autohide = true
    sound = false
    printing = false
    file_transfer = false
    remote_logging = false
  '';
  xpraHtml5 = pkgs.xpra-html5.overrideAttrs (oldAttrs: rec {
    version = "20";
    src = pkgs.fetchFromGitHub {
      owner = "Xpra-org";
      repo = "xpra-html5";
      tag = "v${version}";
      hash = "sha256-sOHUqphOZ15FezQKe1r7DC3vYiwsI0I7IC8YiIv6m8E=";
    };
    patches = (oldAttrs.patches or [ ]) ++ [
      ./desktop/xpra-html5-unsynchronized-keyboard.patch
      ./desktop/xpra-html5-degraded-link-liveness.patch
    ];
    postInstall = (oldAttrs.postInstall or "") + ''
      cat ${xpraHtml5Settings} >> $out/share/xpra/www/default-settings.txt
    '';
  });
  xpra = pkgs.xpra.override { xpra-html5 = xpraHtml5; };
  xpraXorgConf = pkgs.runCommand "xpra-xorg.conf" { } ''
    ${pkgs.gnused}/bin/sed \
      -e 's/VideoRam 768000/VideoRam 65536/' \
      -e 's/Virtual 11520 6318/Virtual 4096 2160/g' \
      ${xpra}/etc/xpra/xorg.conf > $out
  '';

  desktopStartScript = pkgs.writeShellScript "dojo-desktop-start" ''
    desktop_xpra_running() {
      local xpra_pid=

      [ -r /run/dojo/var/desktop-service/xpra.pid ] || return 1
      read -r xpra_pid < /run/dojo/var/desktop-service/xpra.pid || true
      case "$xpra_pid" in
        ""|*[!0-9]*) return 1 ;;
      esac
      [ "$xpra_pid" -gt 1 ] && kill -0 -- "$xpra_pid" 2>/dev/null
    }

    terminate_recorded_xorg() {
      local xvfb_pid_file=
      local xvfb_pid=
      local xvfb_executable=
      local deadline=

      for xvfb_pid_file in /run/dojo/var/desktop-service/sessions/*/xvfb.pid; do
        [ -r "$xvfb_pid_file" ] || continue
        read -r xvfb_pid < "$xvfb_pid_file" || true
        case "$xvfb_pid" in
          ""|*[!0-9]*) continue ;;
        esac
        [ "$xvfb_pid" -gt 1 ] || continue
        kill -0 -- "$xvfb_pid" 2>/dev/null || continue
        xvfb_executable="$(${pkgs.coreutils}/bin/readlink -f "/proc/$xvfb_pid/exe" 2>/dev/null || true)"
        [ "$xvfb_executable" = "${pkgs.xorg-server}/bin/Xorg" ] || continue

        kill -TERM -- "$xvfb_pid" 2>/dev/null || true
        deadline=$((SECONDS + 2))
        while kill -0 -- "$xvfb_pid" 2>/dev/null && (( SECONDS < deadline )); do
          sleep 0.1
        done
        if kill -0 -- "$xvfb_pid" 2>/dev/null; then
          kill -KILL -- "$xvfb_pid" 2>/dev/null || true
        fi
      done
    }

    until [ -f /run/dojo/var/ready ]; do sleep 0.1; done

    export DISPLAY=:0
    export XDG_DATA_DIRS="/run/dojo/share:''${XDG_DATA_DIRS:-/usr/local/share:/usr/share}"
    export XDG_CONFIG_DIRS="/run/dojo/etc/xdg:''${XDG_CONFIG_DIRS:-/etc/xdg}"
    export FONTCONFIG_FILE="${fontsConf}"
    export XDG_RUNTIME_DIR=/run/dojo/var/desktop-service/runtime
    export PATH="${pkgs.xauth}/bin:${pkgs.xorg-server}/bin:$PATH"

    if [ -e /run/dojo/var/desktop-service/Xvnc.pid ] ||
       [ -e /run/dojo/var/desktop-service/novnc.pid ] ||
       [ -e /run/dojo/var/desktop-service/Xvnc.sock ] ||
       [ -e /run/dojo/var/desktop-service/Xvnc.passwd ]; then
      ${service}/bin/dojo-service kill desktop-service/novnc || true
      ${service}/bin/dojo-service kill desktop-service/xfce4-session || true
      ${service}/bin/dojo-service kill desktop-service/Xvnc || true
      rm -f /run/dojo/var/desktop-service/Xvnc.sock \
        /run/dojo/var/desktop-service/Xvnc.passwd \
        /tmp/.X11-unix/X0 \
        /tmp/.X0-lock
    fi

    if ! desktop_xpra_running; then
      ${service}/bin/dojo-service kill desktop-service/xfce4-session || true
      rm -f /run/dojo/var/desktop-service/xpra.pid
      terminate_recorded_xorg
      rm -f /tmp/.X11-unix/X0 /tmp/.X0-lock
      rm -rf /run/dojo/var/desktop-service/sessions/*
    fi

    mkdir -p "$XDG_RUNTIME_DIR" /run/dojo/var/desktop-service/sessions
    chmod 700 "$XDG_RUNTIME_DIR" /run/dojo/var/desktop-service/sessions

    ${service}/bin/dojo-service start desktop-service/xpra \
      ${pkgs.coreutils}/bin/env -u DOJO_AUTH_TOKEN \
        XPRA_CLIENT_CAN_SHUTDOWN=0 \
        XPRA_UNAUTHENTICATED_HELLO_REQUESTS= \
        ${xpra}/bin/xpra monitor $DISPLAY \
          --daemon=no \
          --attach=no \
          --use-display=no \
          --bind=none \
          --bind-ws=0.0.0.0:6080,auth=none \
          --html=${xpraHtml5}/share/xpra/www \
          --http-scripts=off \
          --ssl-upgrade=no \
          --rfb-upgrade=no \
          --mmap=no \
          --source=no \
          --session-name=Desktop \
          --resize-display=yes:1024x768 \
          --pixel-depth=24 \
          --input-devices=xtest \
          --xvfb='${pkgs.xorg-server}/bin/Xorg -novtswitch -logfile $XPRA_SESSION_DIR/Xorg.log -config ${xpraXorgConf} +extension Composite +extension RANDR +extension RENDER -extension DOUBLE-BUFFER -extension GLX -nolisten tcp -noreset -auth $XAUTHORITY' \
          --sessions-dir=/run/dojo/var/desktop-service/sessions \
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

    desktop_ready() {
      for _ in {1..200}; do
        if [ -s /run/dojo/var/desktop-service/xpra.pid ]; then
          read -r xpra_pid < /run/dojo/var/desktop-service/xpra.pid || true
          if [ -n "''${xpra_pid:-}" ] && ! kill -0 "$xpra_pid" 2>/dev/null; then
            return 1
          fi
        fi
        if [ -S /tmp/.X11-unix/X0 ] &&
           ${pkgs.curl}/bin/curl -fs -o /dev/null http://localhost:6080/; then
          return 0
        fi
        sleep 0.1
      done
      return 1
    }

    if ! desktop_ready; then
      ${pkgs.coreutils}/bin/tail -n 50 /run/dojo/var/desktop-service/xpra.log >&2 || true
      ${service}/bin/dojo-service kill desktop-service/xpra || true
      exit 1
    fi

    # By default, xfce4-session invokes dbus-launch without `--config-file`, and it fails to find /etc/dbus-1/session.conf; so we manually specify the config file here.
    ${service}/bin/dojo-service start desktop-service/xfce4-session \
      ${pkgs.dbus}/bin/dbus-launch --sh-syntax --exit-with-session --config-file=${pkgs.dbus}/share/dbus-1/session.conf ${pkgs.xfce4-session}/bin/xfce4-session
  '';

  serviceScript = pkgs.writeShellScript "dojo-desktop" ''
    mkdir -p /run/dojo/var
    exec ${pkgs.util-linux}/bin/flock --close --exclusive \
      /run/dojo/var/desktop-start.lock ${desktopStartScript}
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
    curl
    rsync
  ];
  propagatedBuildInputs = with pkgs; [
    xpra
    xfce
    elementary-xfce-icon-theme # If we include this in `xfce`, we get a "Permission denied" error related to `nix-support/propagated-build-inputs`.
  ];

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
    ln -s ${xpra}/bin/xpra $out/bin/xpra
    ln -s ${pkgs.xfce4-terminal}/bin/xfce4-terminal $out/bin/x-terminal-emulator
    rsync -a --ignore-existing $src/. ${xfce}/. ${pkgs.elementary-xfce-icon-theme}/. $out
    runHook postInstall
  '';
}
