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
  code-server = pkgs.stdenv.mkDerivation {
    name = "code-server";
    src = pkgs.code-server;
    buildInputs = with pkgs; [ nodejs makeWrapper ];
    installPhase = ''
      runHook preInstall

      rgBin=libexec/code-server/lib/vscode/node_modules/@vscode/ripgrep/bin
      mkdir -p $out/$rgBin
      cp ${rgScript} $out/$rgBin/rg
      cp ${pkgs.code-server}/$rgBin/rg $out/$rgBin/rg.orig

      workbenchApiNode=libexec/code-server/lib/vscode/out/vs/workbench/api/node
      mkdir -p $out/$workbenchApiNode
      for f in "extensionHostProcess.js" "extensionHostProcess.js.map"; do
        sed -E 's/(if\s*\(\w+\.\w+\.skipWorkspaceStorageLock\))/if\(true\)/g' ${pkgs.code-server}/$workbenchApiNode/$f > $out/$workbenchApiNode/$f
      done

      mkdir -p $out/bin
      cp -ru ${pkgs.code-server}/libexec/code-server/. $out/libexec/code-server
      makeWrapper ${pkgs.nodejs}/bin/node $out/bin/code-server --add-flags $out/libexec/code-server/out/node/entry.js
      runHook postInstall
    '';
  };

  serviceScript = pkgs.writeScript "dojo-code" ''
    #!${pkgs.bash}/bin/bash

    until [ -f /run/dojo/var/ready ]; do sleep 0.1; done

    ${service}/bin/dojo-service start code-service/code-server \
      ${code-server}/bin/code-server \
        --auth=none \
        --bind-addr=0.0.0.0:8080 \
        --trusted-origins='*' \
        --disable-telemetry \
        --extensions-dir=@out@/share/code-service/extensions

    until ${pkgs.curl}/bin/curl -s localhost:8080 >/dev/null; do sleep 0.1; done
  '';

in pkgs.stdenv.mkDerivation {
  name = "code-service";
  buildInputs = with pkgs; [
    code-server
    bash
    python3
    wget
    curl
    cacert
  ];
  dontUnpack = true;

  installPhase = ''
    runHook preInstall

    mkdir -p $out/bin
    substitute ${serviceScript} $out/bin/dojo-code \
      --subst-var-by out $out
    chmod +x $out/bin/dojo-code
    ln -s ${code-server}/bin/code-server $out/bin/code-server
    ln -s ${code-server}/bin/code-server $out/bin/code

    mkdir -p $out/share/code-service/extensions
    ${pkgs.wget}/bin/wget -P $NIX_BUILD_TOP 'https://github.com/microsoft/vscode-cpptools/releases/download/v1.20.5/cpptools-linux.vsix'
    export HOME=$NIX_BUILD_TOP
    ${code-server}/bin/code-server \
      --auth=none \
      --disable-telemetry \
      --extensions-dir=$out/share/code-service/extensions \
      --install-extension ms-python.python \
      --install-extension $NIX_BUILD_TOP/cpptools-linux.vsix
    chmod +x $out/share/code-service/extensions/ms-vscode.cpptools-*/{bin/cpptools*,bin/libc.so,debugAdapters/bin/OpenDebugAD7,LLVM/bin/clang-*}

    runHook postInstall
  '';
}
