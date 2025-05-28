{
  description = "DOJO Workspace Flake";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-24.11";
    nixpkgs-unstable.url = "github:NixOS/nixpkgs/nixos-unstable";
    nixpkgs-pr-angr-management.url = "github:NixOS/nixpkgs/pull/360310/head";
  };

  outputs =
    {
      self,
      nixpkgs,
      nixpkgs-unstable,
      nixpkgs-pr-angr-management,
    }:
    {
      packages = {
        x86_64-linux =
          let
            system = "x86_64-linux";
            config = {
              allowUnfree = true;
              allowBroken = true; # angr is currently marked "broken" in nixpkgs, but works fine (without unicorn)
            };

            binaryninja-free-overlay = self: super: {
              binaryninja-free = (import nixpkgs-unstable { inherit system config; }).binaryninja-free;
            };

            angr-management-overlay = self: super: {
              angr-management = (import nixpkgs-pr-angr-management { inherit system config; }).angr-management;
            };

            sage-overlay = final: prev: {
              sage = prev.sage.override {
                extraPythonPackages = ps: with ps; [
                  pycryptodome
                  pwntools
                ];
              requireSageTests = false;
              };
            };

            pkgs = import nixpkgs {
              inherit system config;
              overlays = [
                binaryninja-free-overlay
                angr-management-overlay
                sage-overlay
              ];
            };

            init = import ./core/init.nix { inherit pkgs; };
            exec-suid = import ./core/exec-suid.nix { inherit pkgs; };
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
              gawk
              glibc
              glibc.static
              glibcLocales
              gnugrep
              gnused
              hostname
              iproute2
              less
              man
              ncurses
              nettools
              procps
              python3
              util-linux
              wget
              which

              (lib.hiPrio ldd)

              init
              exec-suid
              sudo
              ssh-entrypoint
              service
              code-service
              desktop-service
            ];

            fullPackages = corePackages ++ additional.packages;

            buildDojoEnv =
              name: paths:
              let
                suidPaths = pkgs.lib.unique (
                  builtins.concatLists (
                    map (
                      pkg:
                      if builtins.isAttrs pkg && pkg ? out && pkg.meta ? suid then
                        map (rel: "${pkg.out}/${rel}") pkg.meta.suid
                      else
                        [ ]
                    ) paths
                  )
                );
                suidFile = pkgs.writeTextDir "suid" (pkgs.lib.concatMapStrings (s: s + "\n") suidPaths);
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
