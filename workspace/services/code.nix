{ pkgs }:

let
  service = import ./service.nix { inherit pkgs; };

  rgScript = pkgs.writeScript "rg" ''
    #!${pkgs.python3}/bin/python3

    import sys
    import os

    sys.argv[0] += ".orig"
    if "--follow" in sys.argv:
        sys.argv.remove("--follow")
    os.execv(sys.argv[0], sys.argv)
  '';
  code-server-unwrapped = pkgs.stdenv.mkDerivation {
    inherit (pkgs.code-server) pname version;
    src = pkgs.code-server;
    buildInputs = with pkgs; [
      nodejs
      makeWrapper
    ];
    passthru = {
      inherit (pkgs.code-server) executableName longName;
    };
    installPhase = ''
      runHook preInstall
      rgBin=libexec/code-server/lib/vscode/node_modules/@vscode/ripgrep/bin
      mkdir -p $out/$rgBin
      cp ${rgScript} $out/$rgBin/rg
      cp ${pkgs.code-server}/$rgBin/rg $out/$rgBin/rg.orig
      cp -ru ${pkgs.code-server}/libexec/code-server/. $out/libexec/code-server
      mkdir -p $out/bin
      makeWrapper ${pkgs.nodejs}/bin/node $out/bin/code-server --add-flags $out/libexec/code-server/out/node/entry.js
      runHook postInstall
    '';
  };
  codeExtensions = with pkgs.vscode-extensions; [
    ms-python.python
    ms-vscode.cpptools
  ];
  code-server = pkgs.vscode-with-extensions.override {
    vscode = code-server-unwrapped;
    vscodeExtensions = codeExtensions;
  };

  serviceScript = pkgs.writeScript "dojo-code" ''
    #!${pkgs.bash}/bin/bash

    until [ -f /run/dojo/var/ready ]; do sleep 0.1; done

    if [ -d /run/challenge/share/code/extensions ]; then
      extensionArgs=(--extensions-dir=/run/challenge/share/code/extensions)
    else
      extensionArgs=()
    fi

    ${service}/bin/dojo-service start code-service/code-server \
      ${code-server}/bin/code-server \
        --auth=none \
        --bind-addr=0.0.0.0:8080 \
        --trusted-origins='*' \
        --disable-telemetry \
        "''${extensionArgs[@]}" \
        --config=/dev/null

    until ${pkgs.curl}/bin/curl -fs localhost:8080 >/dev/null; do sleep 0.1; done
  '';

in
pkgs.stdenv.mkDerivation {
  name = "code-service";
  buildInputs = with pkgs; [
    code-server
    bash
    python3
    curl
  ];
  dontUnpack = true;

  installPhase = ''
    runHook preInstall

    mkdir -p $out/bin
    cp ${serviceScript} $out/bin/dojo-code
    ln -s ${code-server}/bin/code-server $out/bin/code-server
    ln -s ${code-server}/bin/code-server $out/bin/code

    runHook postInstall
  '';
}
