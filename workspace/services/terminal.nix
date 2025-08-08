{ pkgs }:

let
  service = import ./service.nix { inherit pkgs; };

  serviceScript = pkgs.writeScript "dojo-terminal" ''
    #!${pkgs.bash}/bin/bash

    until [ -f /run/dojo/var/ready ]; do sleep 0.1; done

    export TERM=xterm-256color
    
    ${service}/bin/dojo-service start terminal-service/ttyd \
      ${pkgs.ttyd}/bin/ttyd \
        --port 7681 \
        --interface 0.0.0.0 \
        --writable \
        -t disableLeaveAlert=true \
        $SHELL --login

    until ${pkgs.curl}/bin/curl -fs localhost:7681 >/dev/null; do sleep 0.1; done
  '';

in pkgs.stdenv.mkDerivation {
  name = "terminal-service";
  buildInputs = with pkgs; [
    ttyd
    bashInteractive
    curl
  ];
  dontUnpack = true;

  installPhase = ''
    runHook preInstall

    mkdir -p $out/bin
    cp ${serviceScript} $out/bin/dojo-terminal
    chmod +x $out/bin/dojo-terminal
    ln -s ${pkgs.ttyd}/bin/ttyd $out/bin/ttyd
    ln -s ${pkgs.ttyd}/bin/ttyd $out/bin/terminal

    runHook postInstall
  '';
}
