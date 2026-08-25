{ pkgs }:

let
  service = import ./service.nix { inherit pkgs; };

  # Prevent VS Code searches from following workspace symlinks into the host
  # filesystem and consuming excessive CPU.
  code-server-patched = pkgs.runCommand "${pkgs.code-server.name}-patched" {
    inherit (pkgs.code-server) pname version meta;
    passthru = {
      inherit (pkgs.code-server) executableName longName;
    };
  } ''
    mkdir -p $out/libexec $out/bin
    cp -r ${pkgs.code-server}/libexec/code-server $out/libexec/code-server

    extensionHost=$out/libexec/code-server/lib/vscode/out/vs/workbench/api/node/extensionHostProcess.js
    chmod u+w "$extensionHost"
    substituteInPlace "$extensionHost" \
      --replace-fail 't.ignoreSymlinks||r.push("--follow")' 't.ignoreSymlinks||r.push("--no-follow")' \
      --replace-fail 't.folderOptions.followSymlinks&&e.push("--follow")' 't.folderOptions.followSymlinks&&e.push("--no-follow")'
    if grep -RqF --include='*.js' -- '--follow' "$out/libexec/code-server/lib/vscode/out"; then
      echo "unpatched --follow argument remains in compiled VS Code" >&2
      exit 1
    fi

    cp ${pkgs.code-server}/bin/code-server $out/bin/code-server
    chmod u+w $out/bin/code-server
    substituteInPlace $out/bin/code-server \
      --replace-fail ${pkgs.code-server} $out
  '';
  codeExtensions = with pkgs.vscode-extensions; [
    ms-python.python
    vadimcn.vscode-lldb
  ];
  code-server = pkgs.vscode-with-extensions.override {
    vscode = code-server-patched;
    vscodeExtensions = codeExtensions;
  };

  serviceScript = pkgs.writeShellScript "dojo-code" ''
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
pkgs.runCommand "code-service" { } ''
  mkdir -p $out/bin
  cp ${serviceScript} $out/bin/dojo-code
  ln -s ${code-server}/bin/code-server $out/bin/code-server
  ln -s ${code-server}/bin/code-server $out/bin/code
''
