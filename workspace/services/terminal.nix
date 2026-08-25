{ pkgs }:

let
  service = import ./service.nix { inherit pkgs; };

  ttyd = pkgs.ttyd.override {
    libwebsockets = pkgs.libwebsockets.overrideAttrs (previousAttrs: {
      cmakeFlags = previousAttrs.cmakeFlags ++ [
        (pkgs.lib.cmakeBool "LWS_WITH_SOCKS5" false)
        (pkgs.lib.cmakeBool "LWS_WITHOUT_CLIENT" true)
      ];
    });
  };

  serviceScript = pkgs.writeShellScript "dojo-terminal" ''
    until [ -f /run/dojo/var/ready ]; do sleep 0.1; done

    export TERM=xterm-256color
    
    ${service}/bin/dojo-service start terminal-service/ttyd \
      ${ttyd}/bin/ttyd \
        --port 7681 \
        --interface 0.0.0.0 \
        --writable \
        -t disableLeaveAlert=true \
        $SHELL --login

    until ${pkgs.curl}/bin/curl -fs localhost:7681 >/dev/null; do sleep 0.1; done
  '';

in
pkgs.runCommand "terminal-service" { } ''
  install -Dm755 ${serviceScript} $out/bin/dojo-terminal
  ln -s ${ttyd}/bin/ttyd $out/bin/ttyd
  ln -s ttyd $out/bin/terminal
''
