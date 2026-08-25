{ pkgs }:

let
  service = import ./service.nix { inherit pkgs; };

  rgScript = pkgs.writeShellScript "rg" ''
    args=()
    for arg in "$@"; do
      if [[ "$arg" == "--follow" ]]; then
        arg="--no-follow"
      fi
      args+=("$arg")
    done
    exec "$0.orig" "''${args[@]}"
  '';
  code-server-unwrapped = pkgs.stdenvNoCC.mkDerivation {
    inherit (pkgs.code-server) pname version;
    dontUnpack = true;
    dontFixup = true;
    passthru = {
      inherit (pkgs.code-server) executableName longName;
    };
    installPhase = ''
      runHook preInstall

      mkdir -p $out/libexec $out/bin
      cp -r ${pkgs.code-server}/libexec/code-server $out/libexec/code-server

      rgBin=$out/libexec/code-server/lib/vscode/node_modules/@vscode/ripgrep/bin
      chmod u+w "$rgBin"
      mv "$rgBin/rg" "$rgBin/rg.orig"
      cp ${rgScript} "$rgBin/rg"

      cp ${pkgs.code-server}/bin/code-server $out/bin/code-server
      chmod u+w $out/bin/code-server
      substituteInPlace $out/bin/code-server \
        --replace-fail ${pkgs.code-server} $out

      runHook postInstall
    '';
  };
  codeExtensions = with pkgs.vscode-extensions; [
    ms-python.python
    vadimcn.vscode-lldb
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
