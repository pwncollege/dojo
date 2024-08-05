{ pkgs }:

let
  windows-script = pkgs.callPackage ./windows-script.nix { };
  windows-vm = pkgs.callPackage ./windows-vm.nix { };
  desktop-win-service = import ./services/desktop-win.nix { inherit pkgs; };
in
{
  packages = [
    windows-script
    windows-vm
    desktop-win-service
  ];
}
