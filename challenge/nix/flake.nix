{
  description = "DOJO Workspace Flake";

  inputs = {
    nixpkgs.url = "nixpkgs/nixos-unstable";
    start-stop-daemon-pkgs.url = "github:supercoolspy/nixpkgs/create-start-stop-daemon";
  };

  outputs = { self, nixpkgs, start-stop-daemon-pkgs }: {
    packages = {
      x86_64-linux = let
        pkgs = import nixpkgs {
          system = "x86_64-linux";
          config = {
            allowUnfree = true;
          };
        };

        start-stop-daemon = import start-stop-daemon-pkgs {
          system = "x86_64-linux";
        };

        dojo-code = let
          serviceScript = pkgs.writeScript "dojo-code" ''
            #!${pkgs.bash}/bin/bash

            export SHELL=${pkgs.bashInteractive}/bin/bash

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
          name = "dojo-code";
          src = pkgs.code-server;
          nativeBuildInputs = [ pkgs.nodejs pkgs.makeWrapper pkgs.bash pkgs.python3 pkgs.bashInteractive start-stop-daemon.start-stop-daemon ];

          installPhase = ''
            runHook preInstall

            rgBin="libexec/code-server/lib/vscode/node_modules/@vscode/ripgrep/bin"

            mkdir -p $out/$rgBin
            cp ${rgScript} $out/$rgBin/rg
            cp ${pkgs.code-server}/$rgBin/rg $out/$rgBin/rg.orig

            cp -ru ${pkgs.code-server}/libexec/code-server/. $out/libexec/code-server

            mkdir -p $out/bin
            makeWrapper "${pkgs.nodejs}/bin/node" "$out/bin/code-server" --add-flags "$out/libexec/code-server/out/node/entry.js"

            cp ${serviceScript} $out/bin/dojo-code
            substituteInPlace $out/bin/dojo-code --replace "CODE_SERVER_PLACEHOLDER" "$out/bin/code-server"

            runHook postInstall
          '';
        };

        dojo-desktop = let
          serviceScript = pkgs.writeScript "dojo-desktop" ''
            #!${pkgs.bash}/bin/bash

            export DISPLAY=:42

            cleanup() {
                kill $(jobs -p)
            }
            trap cleanup EXIT SIGHUP SIGINT SIGTERM

            Xvnc $DISPLAY -localhost 0 -rfbport 5900 -geometry 1024x768 -depth 24 -SecurityTypes None &
            novnc &
            sleep 1
            fluxbox
          '';

        in pkgs.stdenv.mkDerivation {
          name = "dojo-desktop";
          buildInputs = [ pkgs.bash ];
          propagatedBuildInputs = [
            pkgs.tigervnc
            pkgs.novnc
            pkgs.fluxbox
            pkgs.xterm
            pkgs.fontconfig
            pkgs.font-awesome
            pkgs.inconsolata
            pkgs.dejavu_fonts
          ];
          dontUnpack = true;

          installPhase = ''
            runHook preInstall
            mkdir -p $out/bin
            cp ${serviceScript} $out/bin/dojo-desktop
            runHook postInstall
          '';
        };

        pythonEnv = pkgs.python3.withPackages (ps: with ps; [
          requests
          flask
          pwntools
        ]);

        minimalBuildInputs = with pkgs; [
          util-linux
          procps
          ncurses
          hostname
          bashInteractive

          dojo-code
          dojo-desktop
        ];

        fullBuildInputs = minimalBuildInputs ++ (with pkgs; [
          pythonEnv

          ghidra
          ida-free
          radare2

          wireshark
          nmap
          tcpdump
        ]);

      in {
        default = pkgs.mkShell {
          name = "dojo";
          buildInputs = minimalBuildInputs;
        };
        full = pkgs.mkShell {
          name = "dojo";
          buildInputs = fullBuildInputs;
        };
      };
    };

    defaultPackage.x86_64-linux = self.packages.x86_64-linux;
  };
}