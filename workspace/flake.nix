{
  description = "DOJO Workspace Flake";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-24.05";
  };

  outputs = { self, nixpkgs }: {
    packages = {
      x86_64-linux = let
        pkgs = import nixpkgs {
          system = "x86_64-linux";
          config = {
            allowUnfree = true;
          };
        };

        code-service = import ./services/code.nix { inherit pkgs; };
        desktop-service = import ./services/desktop.nix { inherit pkgs; };

        additional = import ./additional/additional.nix { inherit pkgs; };

        coreBuildInputs = with pkgs; [
          bashInteractive
          cacert
          curl
          glibcLocales
          hostname
          iproute2
          man
          ncurses
          procps
          util-linux
          wget
          which

          code-service
          desktop-service
        ];

        fullBuildInputs = coreBuildInputs ++ additional.buildInputs;

        mkDojoShell = name: buildInputs: pkgs.mkShell {
          name = "dojo-workspace-${name}";
          inherit buildInputs;

          shellHook = ''
            export SHELL=${pkgs.bashInteractive}/bin/bash
            export LC_ALL=C.UTF-8
          '';
        };

      in {
        default = mkDojoShell "core" coreBuildInputs;
        core = mkDojoShell "core" coreBuildInputs;
        full = mkDojoShell "full" fullBuildInputs;
      };
    };

    defaultPackage.x86_64-linux = self.packages.x86_64-linux;
  };
}
