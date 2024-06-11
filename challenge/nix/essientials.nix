{ pkgs ? import <nixpkgs> {} }:
with pkgs;
mkShell {
  nativeBuildInputs = [ libgcc gnumake42 curl sudo wget unzip ];
  buildInputs = [ cacert ];
  shellHook = ''
  ln -sr $(which gcc) /nix/bin/gcc
  ln -sr $(which curl) /nix/bin/curl
  ln -sr $(which sudo) /nix/bin/sudo
  ln -sr $(which wget) /nix/bin/wget
  ln -sr $(which unzip) /nix/bin/unzip
  '';
}
