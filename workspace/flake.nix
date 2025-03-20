{
  description = "DOJO Workspace Flake";

  inputs = {
    nixpkgs.url = "git+file:///opt/nixpkgs-24.11";
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
              allowBroken = true;  # angr is currently marked "broken" in nixpkgs, but works fine (without unicorn)
            };
            pkgs-backports = import nixpkgs-backports { inherit system config; };
            backports-overlay = self: super: {
              inherit (pkgs-backports) angr-management binaryninja-free;
            };
            pkgs = import nixpkgs {
              inherit system config;
              overlays = [ backports-overlay ];
            };

            init = import ./core/init.nix { inherit pkgs; };
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
            ];

            fullPackages = corePackages ++ additional.packages;

            buildDojoEnv = name: paths:
              let
                collectSuidPaths = pkg:
                  if builtins.isAttrs pkg then
                    let
                      selfEntries =
                        if pkg.meta ? suid then
                          map (rel: "${pkg.out}/${rel}") pkg.meta.suid
                        else []
                      ;
                      childEntries = builtins.concatLists (map collectSuidPaths (builtins.attrValues pkg));
                    in selfEntries ++ childEntries
                  else [];
                suidPaths = pkgs.lib.unique (builtins.concatLists (map collectSuidPaths paths));
                suidFileText = builtins.concatStringsSep "\n" suidPaths;
                suidFile = pkgs.writeText "suid" suidFileText;
              in
                pkgs.buildEnv {
                  name = "dojo-workspace-${name}";
                  paths = paths ++ [ suidFile ];
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
