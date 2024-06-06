{ pkgs ? import <nixpkgs> {} }:
with pkgs;
mkShell {
  nativeBuildInputs = [ libgcc gnumake42 curl sudo wget unzip ];
  buildInputs = [ cacert ];
}
