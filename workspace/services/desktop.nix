{ pkgs }:

let
  service = import ./service.nix { inherit pkgs; };

  novncOverlay = self: super: {
    novnc = super.novnc.overrideAttrs (old: {
      patches = (old.patches or []) ++ [
        # Revert https://github.com/novnc/noVNC/pull/1672
        (super.writeText "reconnect_patch.diff" ''
          --- a/share/webapps/novnc/app/ui.js
          +++ b/share/webapps/novnc/app/ui.js
          @@ -1,3 +1,3 @@
          -if (UI.getSetting('reconnect', false)
          +else if (UI.getSetting('reconnect', false)
        '')
      ];
    });
  };

  overlays = [novncOverlay];
  patchedPkgs = import pkgs.path { inherit overlays; };

  serviceScript = pkgs.writeScript "dojo-desktop" ''
    #!${pkgs.bash}/bin/bash

    until [ -f /run/dojo/ready ]; do sleep 0.1; done

    export DISPLAY=:0
    export XDG_DATA_DIRS="/run/current-system/sw/share:''${XDG_DATA_DIRS:-/usr/local/share:/usr/share}"
    export XDG_CONFIG_DIRS="/run/current-system/sw/etc/xdg:''${XDG_CONFIG_DIRS:-/etc/xdg}"

    auth_token="$(cat /run/dojo/auth_token)"
    password_interact="$(printf 'desktop-interact' | ${pkgs.openssl}/bin/openssl dgst -sha256 -hmac "$auth_token" | awk '{print $2}' | head -c 8)"
    password_view="$(printf 'desktop-view' | ${pkgs.openssl}/bin/openssl dgst -sha256 -hmac "$auth_token" | awk '{print $2}' | head -c 8)"

    mkdir -p /run/dojo/desktop-service
    printf '%s\n%s\n' "$password_interact" "$password_view" | ${pkgs.tigervnc}/bin/vncpasswd -f > /run/dojo/desktop-service/Xvnc.passwd

    ${service}/bin/service start desktop-service/Xvnc \
      ${pkgs.tigervnc}/bin/Xvnc \
        $DISPLAY \
        -localhost 0 \
        -rfbunixpath /run/dojo/desktop-service/Xvnc.sock \
        -rfbauth /run/dojo/desktop-service/Xvnc.passwd \
        -nolisten tcp \
        -geometry 1024x768 \
        -depth 24

    ${service}/bin/service start desktop-service/novnc \
      ${patchedPkgs.novnc}/bin/novnc \
        --vnc --unix-target=/run/dojo/desktop-service/Xvnc.sock \
        --listen 6080

    until [ -e /tmp/.X11-unix/X0 ]; do sleep 0.1; done
    until ${pkgs.curl}/bin/curl -s localhost:6080 >/dev/null; do sleep 0.1; done

    # By default, xfce4-session invokes dbus-launch without `--config-file`, and it fails to find /etc/dbus-1/session.conf; so we manually specify the config file here.
    ${service}/bin/service start desktop-service/xfce4-session \
      ${pkgs.dbus}/bin/dbus-launch --sh-syntax --exit-with-session --config-file=${pkgs.dbus}/share/dbus-1/session.conf ${pkgs.xfce.xfce4-session}/bin/xfce4-session
  '';

  xfce = pkgs.symlinkJoin {
    name = "xfce";
    paths = with pkgs.xfce; [
      xfce4-session
      xfce4-settings
      xfce4-terminal
      xfce4-panel
      xfce4-appfinder
      xfwm4
      xfdesktop
      xfconf
      exo
      thunar
    ] ++ (with pkgs; [
      dbus
      dejavu_fonts
      blackbird
    ]);
  };

in pkgs.stdenv.mkDerivation {
  name = "desktop-service";
  src = ./desktop;

  buildInputs = with pkgs; [
    bash
    openssl
    curl
    rsync
  ];
  propagatedBuildInputs = with pkgs; [
    tigervnc
    patchedPkgs.novnc
    xfce
    elementary-xfce-icon-theme  # If we include this in `xfce`, we get a "Permission denied" error related to `nix-support/propagated-build-inputs`.
  ];

  dontMoveSystemdUserUnits = true;  # We run into an issue where we `mv` "the same file".

  unpackPhase = ''
    runHook preUnpack
    cp -r $src $PWD
    runHook postUnpack
  '';

  installPhase = ''
    runHook preInstall
    mkdir -p $out/bin
    cp ${serviceScript} $out/bin/dojo-desktop
    rsync -a --ignore-existing $src/. ${xfce}/. ${pkgs.elementary-xfce-icon-theme}/. $out
    runHook postInstall
  '';
}
