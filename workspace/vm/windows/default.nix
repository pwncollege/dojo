{ pkgs }:

let
  windows-script = import ./windows-script.nix { inherit pkgs; };
  windows-vm = pkgs.callPackage ./windows-vm.nix { };
  desktop-windows-service = import ../../services/desktop-windows.nix { inherit pkgs; };
in
{
  packages = [
    windows-script
    windows-vm
    desktop-windows-service
  ];
}
