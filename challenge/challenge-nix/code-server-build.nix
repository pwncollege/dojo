{ pkgs ? import <nixpkgs> {} }:
with pkgs;

mkShell {
  # Riggrep patch requires python
  nativeBuildInputs = [ python312 code-server ];
}
