{
  description = "DOJO Workspace Flake";

  inputs = {
    nixpkgs.url = "git+file:///opt/nixpkgs-24.05";
  };

  outputs = { self, nixpkgs }: {
    packages = {
      x86_64-linux =
        let
          pkgs = import nixpkgs {
            system = "x86_64-linux";
            config = {
              allowUnfree = true;
            };
          };

          init = import ./core/init.nix { inherit pkgs; };
          suid-interpreter = import ./core/suid-interpreter.nix { inherit pkgs; };
          sudo = import ./core/sudo.nix { inherit pkgs; };
          ssh-entrypoint = import ./core/ssh-entrypoint.nix { inherit pkgs; };
          service = import ./services/service.nix { inherit pkgs; };
          code-service = import ./services/code.nix { inherit pkgs; };
          desktop-service = import ./services/desktop.nix { inherit pkgs; };

          ldd = (pkgs.writeShellScriptBin "ldd" ''
            ldd=/usr/bin/ldd
            for arg in "$@"; do
              case "$arg" in
                -*) ;;
                *)
                  case "$(readlink -f "$arg")" in
                    /nix/store/*) ldd="${pkgs.glibc.bin}/bin/ldd" ;;
                  esac
                  ;;
              esac
            done
            exec "$ldd" "$@"
          '');

          additional = import ./additional/additional.nix { inherit pkgs; };

          corePackages = with pkgs; [
            bashInteractive
            cacert
            coreutils
            curl
            findutils
            glibc
            glibcLocales
            gawk
            gnugrep
            gnused
            hostname
            iproute2
            less
            man
            nettools
            ncurses
            procps
            python3
            util-linux
            wget
            which

            (lib.hiPrio ldd)

            init
            sudo
            ssh-entrypoint
            service
            code-service
            desktop-service
            suid-interpreter
          ];

          fullPackages = corePackages ++ additional.packages;

          buildDojoEnv = name: paths: pkgs.buildEnv {
            name = "dojo-workspace-${name}";
            inherit paths;
          };

        in
        {
          default = buildDojoEnv "core" corePackages;
          core = buildDojoEnv "core" corePackages;
          full = buildDojoEnv "full" fullPackages;
        };
    };

    defaultPackage.x86_64-linux = self.packages.x86_64-linux;
  };
}
