{ pkgs }:

let
  service = import ./service.nix { inherit pkgs; };

  serviceScript = pkgs.writeScript "dojo-desktop" ''
    #!${pkgs.bash}/bin/bash

    export DISPLAY=:0

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
      ${pkgs.novnc}/bin/novnc \
        --vnc --unix-target=/run/dojo/desktop-service/Xvnc.sock \
        --listen 6080

    until [ -e /tmp/.X11-unix/X0 ]; do sleep 0.1; done
    until ${pkgs.curl}/bin/curl -s localhost:6080 >/dev/null; do sleep 0.1; done

    ${service}/bin/service start desktop-service/fluxbox \
      ${pkgs.fluxbox}/bin/fluxbox
  '';

in pkgs.stdenv.mkDerivation {
  name = "desktop-service";
  buildInputs = [ pkgs.bash pkgs.openssl pkgs.curl ];
  propagatedBuildInputs = [
    pkgs.tigervnc
    pkgs.novnc
    pkgs.fluxbox
    pkgs.xterm
  ];
  dontUnpack = true;

  installPhase = ''
    runHook preInstall
    mkdir -p $out/bin
    cp ${serviceScript} $out/bin/dojo-desktop
    runHook postInstall
  '';
}
