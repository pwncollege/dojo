{ pkgs }:

let
  service = import ./service.nix { inherit pkgs; };

  serviceScript = pkgs.writeScript "dojo-code" ''
    #!${pkgs.bash}/bin/bash

    ${service}/bin/service start code-service/code-server \
      @out@/bin/code-server \
        --auth=none \
        --bind-addr=0.0.0.0:8080 \
        --trusted-origins='*' \
        --disable-telemetry \
        --extensions-dir=@out@/share/code-service/extensions

    until ${pkgs.curl}/bin/curl -s localhost:8080 >/dev/null; do sleep 0.1; done
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
  nativeBuildInputs = [ pkgs.nodejs pkgs.makeWrapper pkgs.bash pkgs.python3 pkgs.wget pkgs.curl pkgs.cacert ];

  installPhase = ''
    runHook preInstall

    rgBin=libexec/code-server/lib/vscode/node_modules/@vscode/ripgrep/bin

    mkdir -p $out/$rgBin
    cp ${rgScript} $out/$rgBin/rg
    cp ${pkgs.code-server}/$rgBin/rg $out/$rgBin/rg.orig

    cp -ru ${pkgs.code-server}/libexec/code-server/. $out/libexec/code-server

    mkdir -p $out/bin
    makeWrapper ${pkgs.nodejs}/bin/node $out/bin/code-server --add-flags $out/libexec/code-server/out/node/entry.js
    cp $out/bin/code-server $out/bin/code

    substitute ${serviceScript} $out/bin/dojo-code \
      --subst-var-by out $out

    mkdir -p $out/share/code-service/extensions
    ${pkgs.wget}/bin/wget -P $NIX_BUILD_TOP 'https://github.com/microsoft/vscode-cpptools/releases/download/v1.20.5/cpptools-linux.vsix'
    export HOME=$NIX_BUILD_TOP
    $out/bin/code-server \
      --auth=none \
      --disable-telemetry \
      --extensions-dir=$out/share/code-service/extensions \
      --install-extension ms-python.python \
      --install-extension $NIX_BUILD_TOP/cpptools-linux.vsix
    chmod +x $out/share/code-service/extensions/ms-vscode.cpptools-*/{bin/cpptools*,bin/libc.so,debugAdapters/bin/OpenDebugAD7,LLVM/bin/clang-*}

    runHook postInstall
  '';
}
