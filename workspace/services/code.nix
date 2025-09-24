{ pkgs }:

let
  service = import ./service.nix { inherit pkgs; };
  themes = import ../themes { inherit pkgs; };

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
      cp -ru ${pkgs.code-server}/libexec/code-server/. $out/libexec/code-server
      mkdir -p $out/bin
      makeWrapper ${pkgs.nodejs}/bin/node $out/bin/code-server --add-flags $out/libexec/code-server/out/node/entry.js
      runHook postInstall
    '';
  };

  serviceScript = pkgs.writeScript "dojo-code" ''
    #!${pkgs.bash}/bin/bash

    until [ -f /run/dojo/var/ready ]; do sleep 0.1; done

    if [ -d /run/challenge/share/code/extensions ]; then
      EXTENSIONS_DIR="/run/challenge/share/code/extensions"
    else
      EXTENSIONS_DIR="/home/hacker/.vscode-server/extensions"
      mkdir -p "$(dirname "$EXTENSIONS_DIR")"
      mkdir -p "$EXTENSIONS_DIR"
      # Fix permissions for hacker user
      chown -R hacker:hacker /home/hacker/.vscode-server 2>/dev/null || true
      # Copy pre-installed extensions if they don't exist
      if [ ! -d "$EXTENSIONS_DIR/ms-python.python" ]; then
        cp -r @out@/share/code/extensions/* "$EXTENSIONS_DIR/" 2>/dev/null || true
        # Fix ownership and permissions for extensions
        chown -R hacker:hacker "$EXTENSIONS_DIR" 2>/dev/null || true
        chmod -R u+w "$EXTENSIONS_DIR" 2>/dev/null || true
        echo "[CODE] Extensions copied and permissions fixed" >&2
      fi
    fi

    # Load theme and prepare workspace settings
    THEME_NAME="''${TERMINAL_THEME_NAME:-matrix}"
    echo "[CODE] Loading theme: $THEME_NAME" >&2

    case "$THEME_NAME" in
      "matrix")
        THEME_SETTINGS=$(cat ${themes.getVSCodeTheme "matrix"})
        ;;
      "amethyst")
        THEME_SETTINGS=$(cat ${themes.getVSCodeTheme "amethyst"})
        ;;
      "solarized")
        THEME_SETTINGS=$(cat ${themes.getVSCodeTheme "solarized"})
        ;;
      "everforest")
        THEME_SETTINGS=$(cat ${themes.getVSCodeTheme "everforest"})
        ;;
      "gruvbox")
        THEME_SETTINGS=$(cat ${themes.getVSCodeTheme "gruvbox"})
        ;;
      "perplexity")
        THEME_SETTINGS=$(cat ${themes.getVSCodeTheme "perplexity"})
        ;;
      *)
        THEME_SETTINGS=$(cat ${themes.getVSCodeTheme "matrix"})
        echo "[CODE] Unknown theme '$THEME_NAME', using matrix" >&2
        ;;
    esac

    # Setup workspace settings directory for default theme
    # This can be overridden by user settings
    WORKSPACE_DIR="/home/hacker"
    WORKSPACE_SETTINGS_DIR="$WORKSPACE_DIR/.vscode"
    mkdir -p "$WORKSPACE_SETTINGS_DIR"

    # Ensure directory is owned by hacker user
    chown -R 1000:1000 "$WORKSPACE_SETTINGS_DIR" 2>/dev/null || true

   echo "$THEME_SETTINGS" > "$WORKSPACE_SETTINGS_DIR/settings.json"
    chown 1000:1000 "$WORKSPACE_SETTINGS_DIR/settings.json" 2>/dev/null || true


    # Final ownership check to ensure everything is owned by hacker user
    chown -R 1000:1000 "$WORKSPACE_SETTINGS_DIR" 2>/dev/null || true

    ${service}/bin/dojo-service start code-service/code-server \
      ${code-server}/bin/code-server \
        --auth=none \
        --bind-addr=0.0.0.0:8080 \
        --trusted-origins='*' \
        --disable-telemetry \
        --extensions-dir=$EXTENSIONS_DIR \
        --config=/dev/null


    until ${pkgs.curl}/bin/curl -fs localhost:8080 >/dev/null; do sleep 0.1; done
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

    echo "-------------------------- Installing extensions ---------------------------" >&2
    mkdir -p $out/share/code/extensions
    export HOME=$NIX_BUILD_TOP

    ${code-server}/bin/code-server \
      --auth=none \
      --disable-telemetry \
      --extensions-dir=$out/share/code/extensions \
      --install-extension vatsalsy.gruvbox-crisp-tex \
      --install-extension sainnhe.everforest \
      --install-extension mangeshrex.everblush \
      --install-extension sjsepan.sjsepan-matrixish
    echo "-------------------------- Done installing extensions ---------------------------" >&2

    runHook postInstall
  '';
}
