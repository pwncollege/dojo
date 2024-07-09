{ pkgs }:

let
  windows-script = pkgs.callPackage ./windows-script.nix { };
in
{
  packages = [
    windows-script
  ];
}
