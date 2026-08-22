{
  description = "DOJO Workspace Flake";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-26.05";
    nixpkgs-pr-angr.url = "github:NixOS/nixpkgs/pull/554851/head";
    pwndbg = {
      url = "github:pwndbg/pwndbg";
      inputs.nixpkgs.follows = "nixpkgs";
    };
  };

  outputs =
    {
      self,
      nixpkgs,
      nixpkgs-pr-angr,
      pwndbg,
    }:
    {
      packages = {
        x86_64-linux =
          let
            system = "x86_64-linux";
            config = {
              allowUnfree = true;
            };

            workspace-overlays = import ./overlays {
              inherit
                nixpkgs-pr-angr
                pwndbg
                system
                ;
            };

            pkgs = import nixpkgs {
              inherit system config;
              overlays = workspace-overlays;
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
            ghostty-terminfo = import ./core/ghostty-terminfo.nix { inherit pkgs; };

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
              ghostty-terminfo
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
              openssh
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
            cli = buildDojoEnv "cli" [ dojo-cli ];
            full = buildDojoEnv "full" fullPackages;
          };
      };
    };
}
