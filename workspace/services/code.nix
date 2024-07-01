{ pkgs }:

let
  serviceScript = pkgs.writeScript "dojo-code" ''
    #!${pkgs.bash}/bin/bash

    exec CODE_SERVER_PLACEHOLDER --auth=none --bind-addr=0.0.0.0:8080 --disable-telemetry
    # --extensions-dir=/opt/code-server/extensions
  '';

  rgScript = pkgs.writeScript "rg" ''
    #!${pkgs.python3}/bin/python3

    import sys
    import os

    sys.argv[0] += ".orig"
    if "--follow" in sys.argv:
        sys.argv.remove("--follow")
    os.execv(sys.argv[0], sys.argv)
  '';

in pkgs.stdenv.mkDerivation {
  name = "code-service";
  src = pkgs.code-server;
  nativeBuildInputs = [ pkgs.nodejs pkgs.makeWrapper pkgs.bash pkgs.python3 ];

  installPhase = ''
    runHook preInstall

    rgBin="libexec/code-server/lib/vscode/node_modules/@vscode/ripgrep/bin"

    mkdir -p $out/$rgBin
    cp ${rgScript} $out/$rgBin/rg
    cp ${pkgs.code-server}/$rgBin/rg $out/$rgBin/rg.orig

    cp -ru ${pkgs.code-server}/libexec/code-server/. $out/libexec/code-server

    mkdir -p $out/bin
    makeWrapper "${pkgs.nodejs}/bin/node" "$out/bin/code-server" --add-flags "$out/libexec/code-server/out/node/entry.js"
    cp $out/bin/code-server $out/bin/code

    cp ${serviceScript} $out/bin/dojo-code
    substituteInPlace $out/bin/dojo-code --replace "CODE_SERVER_PLACEHOLDER" "$out/bin/code-server"

    runHook postInstall
  '';
}
