{
  description = "pwn.college dojo NixOS appliance";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-26.05";

    ctfd = {
      url = "github:CTFd/CTFd/3.6.0";
      flake = false;
    };

    pyproject-nix = {
      url = "github:pyproject-nix/pyproject.nix";
      inputs.nixpkgs.follows = "nixpkgs";
    };

    uv2nix = {
      url = "github:pyproject-nix/uv2nix";
      inputs.nixpkgs.follows = "nixpkgs";
      inputs.pyproject-nix.follows = "pyproject-nix";
    };

    pyproject-build-systems = {
      url = "github:pyproject-nix/build-system-pkgs";
      inputs.nixpkgs.follows = "nixpkgs";
      inputs.pyproject-nix.follows = "pyproject-nix";
      inputs.uv2nix.follows = "uv2nix";
    };

  };

  outputs =
    inputs@{
      self,
      nixpkgs,
      pyproject-nix,
      uv2nix,
      pyproject-build-systems,
      ...
    }:
    let
      system = "x86_64-linux";
      pkgs = import nixpkgs {
        inherit system;
        config.allowUnfree = true;
      };
      dojoPackages = pkgs.callPackage ./nix/packages.nix {
        inherit
          inputs
          pyproject-nix
          pyproject-build-systems
          uv2nix
          ;
        dojoSource = self;
      };
      dojoSystem = nixpkgs.lib.nixosSystem {
        inherit system;
        specialArgs = {
          inherit dojoPackages inputs;
          dojoSource = self;
        };
        modules = [
          "${nixpkgs}/nixos/modules/virtualisation/docker-image.nix"
          ./nix/module.nix
        ];
      };
    in
    {
      nixosConfigurations.dojo = dojoSystem;

      packages.${system} =
        builtins.removeAttrs dojoPackages [
          "override"
          "overrideDerivation"
        ]
        // {
          default = dojoSystem.config.system.build.tarball;
          dojo-image = dojoSystem.config.system.build.tarball;
        };

      formatter.${system} = pkgs.nixfmt-tree;
    };
}
