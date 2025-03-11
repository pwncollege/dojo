{
  description = "DOJO Workspace Flake";

  inputs = {
    nixpkgs.url = "git+file:///opt/nixpkgs-24.11";
    nixpkgs-unstable.url = "git+file:///opt/nixpkgs-unstable";
    nixpkgs-backports.url = "git+file:///opt/nixpkgs-backports";
  };

  outputs =
    {
      self,
      nixpkgs,
      nixpkgs-backports,
    }:
    {
      packages = {
        x86_64-linux =
          let
            system = "x86_64-linux";
            config = {
              allowUnfree = true;
            };
            pkgs-unstable = import nixpkgs-unstable { inherit system config; };
            unstable-overlay = self: super: {
              python3Packages = super.python3Packages // {
                angr = pkgs-unstable.python3Packages.angr;
              };
            };
            pkgs-backports = import nixpkgs-backports { inherit system config; };
            backports-overlay = self: super: {
                inherit (pkgs-backports) angr-management binaryninja-free;
            };
            pkgs = import nixpkgs {
              inherit system config;
              overlays = [ unstable-overlay backports-overlay ];
            };

            init = import ./core/init.nix { inherit pkgs; };
            suid-interpreter = import ./core/suid-interpreter.nix { inherit pkgs; };
            sudo = import ./core/sudo.nix { inherit pkgs; };
            ssh-entrypoint = import ./core/ssh-entrypoint.nix { inherit pkgs; };
            service = import ./services/service.nix { inherit pkgs; };
            code-service = import ./services/code.nix { inherit pkgs; };
            desktop-service = import ./services/desktop.nix { inherit pkgs; };

            ldd = pkgs.writeShellScriptBin "ldd" ''
              ldd=/usr/bin/ldd
              for arg in "$@"; do
                case "$arg" in
                  -*) ;;
                  *)
                    case "$(readlink -f "$arg")" in
                      /nix/store/*) ldd="${pkgs.lib.getBin pkgs.glibc}/bin/ldd" ;;
                    esac
                    ;;
                esac
              done
              exec "$ldd" "$@"
            '';

            additional = import ./additional/additional.nix { inherit pkgs; };

            corePackages = with pkgs; [
              bashInteractive
              cacert
              coreutils
              curl
              findutils
              glibc
              glibc.static
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

            buildDojoEnv =
              name: paths:
              pkgs.buildEnv {
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
