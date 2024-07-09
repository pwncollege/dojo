{ pkgs }:

let
  windows-script = pkgs.callPackage ./windows-script.nix { };
  windows-vm = pkgs.callPackage ./windows-vm.nix { };
in
{
  packages = [
    windows-script
    windows-vm
  ];
}
