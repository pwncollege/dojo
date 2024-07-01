{ pkgs }:

let
  service = import ./service.nix { inherit pkgs; };

  serviceScript = pkgs.writeScript "dojo-desktop" ''
    #!${pkgs.bash}/bin/bash

    export DISPLAY=:0

    ${service}/bin/service start desktop-service/Xvnc \
      ${pkgs.tigervnc}/bin/Xvnc \
        $DISPLAY \
        -localhost 0 \
        -rfbport 5900 \
        -geometry 1024x768 \
        -depth 24 \
        -SecurityTypes None \

    ${service}/bin/service start desktop-service/novnc \
      ${pkgs.novnc}/bin/novnc \
        --vnc localhost:5900

    until [ -e /tmp/.X11-unix/X0 ]; do sleep 0.1; done
    until ${pkgs.curl}/bin/curl -s localhost:6080 >/dev/null; do sleep 0.1; done

    ${service}/bin/service start desktop-service/fluxbox \
      ${pkgs.fluxbox}/bin/fluxbox
  '';

in pkgs.stdenv.mkDerivation {
  name = "desktop-service";
  buildInputs = [ pkgs.bash pkgs.curl ];
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
