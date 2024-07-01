{ pkgs }:

let
  serviceScript = pkgs.writeScript "dojo-desktop" ''
    #!${pkgs.bash}/bin/bash

    export DISPLAY=:42

    cleanup() {
        kill $(jobs -p)
    }
    trap cleanup EXIT SIGHUP SIGINT SIGTERM

    Xvnc $DISPLAY -localhost 0 -rfbport 5900 -geometry 1024x768 -depth 24 -SecurityTypes None &
    novnc &
    sleep 1
    fluxbox
  '';

in pkgs.stdenv.mkDerivation {
  name = "desktop-service";
  buildInputs = [ pkgs.bash ];
  propagatedBuildInputs = [
    pkgs.tigervnc
    pkgs.novnc
    pkgs.fluxbox
    pkgs.xterm
    pkgs.fontconfig
    pkgs.font-awesome
    pkgs.inconsolata
    pkgs.dejavu_fonts
  ];
  dontUnpack = true;

  installPhase = ''
    runHook preInstall
    mkdir -p $out/bin
    cp ${serviceScript} $out/bin/dojo-desktop
    runHook postInstall
  '';
}
