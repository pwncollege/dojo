{
  description = "DOJO Workspace Flake";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-25.11";
    nixpkgs-24-11.url = "github:NixOS/nixpkgs/nixos-24.11";
    nixpkgs-pr-angr-management.url = "github:NixOS/nixpkgs/pull/360310/head";
    angr.url = "github:pwncollege/nixpkgs/update/angr";
    pwndbg.url = "github:pwndbg/pwndbg";
  };

  outputs =
    {
      self,
      nixpkgs,
      nixpkgs-24-11,
      nixpkgs-pr-angr-management,
      pwndbg,
      angr,
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

            angr-management-overlay = self: super: {
              angr-management = (import nixpkgs-pr-angr-management { inherit system config; }).angr-management;
            };

            angr-overlay = self: super: {
              python3 = super.python3.override {
                packageOverrides = final: prev: {
                  angr = (import angr { inherit system config; }).python3Packages.angr;
                };
              };
              python3Packages = self.python3.pkgs;
            };

            ida-free-overlay = self: super: {
              ida-free = (import nixpkgs-24-11 { inherit system config; }).ida-free;
            };

            pwndbg-overlay = self: super: {
              pwndbg = pwndbg.packages.${system}.pwndbg;
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
                angr-management-overlay
                angr-overlay
                ida-free-overlay
                sage-overlay
                pwndbg-overlay
              ];
            };

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

            exec-suid = import ./core/exec-suid.nix { inherit pkgs; };
            init = import ./core/init.nix { inherit pkgs; };
            ssh-entrypoint = import ./core/ssh-entrypoint.nix { inherit pkgs; };
            sudo = import ./core/sudo.nix { inherit pkgs; };
            dojo-cli = import ./core/dojo-cli.nix { inherit pkgs; };

            service = import ./services/service.nix { inherit pkgs; };
            code-service = import ./services/code.nix { inherit pkgs; };
            desktop-service = import ./services/desktop.nix { inherit pkgs; };
            terminal-service = import ./services/terminal.nix { inherit pkgs; };

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

              exec-suid
              init
              ssh-entrypoint
              sudo

              service
              code-service
              desktop-service
              terminal-service
              dojo-cli
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
