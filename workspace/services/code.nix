{ pkgs }:

let
  service = import ./service.nix { inherit pkgs; };

  code-server-patched = pkgs.stdenvNoCC.mkDerivation {
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

      vscodeOut=$out/libexec/code-server/lib/vscode/out
      chmod -R u+w "$vscodeOut"
      followCount=$(grep -RhoF --include='*.js' -- '--follow' "$vscodeOut" | wc -l || true)
      if [ "$followCount" -lt 2 ]; then
        echo "expected at least two compiled --follow arguments, found $followCount" >&2
        exit 1
      fi
      grep -RlZ --include='*.js' -F -- '--follow' "$vscodeOut" \
        | xargs -0 sed -i 's/--follow/--no-follow/g'
      if grep -RqF --include='*.js' -- '--follow' "$vscodeOut"; then
        echo "unpatched --follow argument remains in compiled VS Code" >&2
        exit 1
      fi

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
    vscode = code-server-patched;
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
