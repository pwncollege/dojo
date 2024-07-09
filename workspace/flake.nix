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

        init = import ./init.nix { inherit pkgs; };
        service = import ./services/service.nix { inherit pkgs; };
        code-service = import ./services/code.nix { inherit pkgs; };
        desktop-service = import ./services/desktop.nix { inherit pkgs; };

        additional = import ./additional/additional.nix { inherit pkgs; };
        windows = import ./vm/windows/windows.nix { inherit pkgs; };

        corePackages = with pkgs; [
          bashInteractive
          cacert
          coreutils
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

          init
          service
          code-service
          desktop-service
        ];

        fullPackages = corePackages ++ additional.packages ++ windows.packages;

        buildDojoEnv = name: paths: pkgs.buildEnv {
          name = "dojo-workspace-${name}";
          inherit paths;
        };

      in {
        default = buildDojoEnv "core" corePackages;
        core = buildDojoEnv "core" corePackages;
        full = buildDojoEnv "full" fullPackages;
      };
    };

    defaultPackage.x86_64-linux = self.packages.x86_64-linux;
  };
}
