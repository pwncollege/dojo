{ pkgs }:

let
  windows-script = import ./windows-script.nix { inherit pkgs; };
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
