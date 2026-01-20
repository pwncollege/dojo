{ pkgs }:

let
  python = pkgs.python3.withPackages (ps: [ ps.requests ]);
in
pkgs.writeShellScriptBin "dojo" ''
  exec ${python}/bin/python3 ${./dojo-cli.py} "$@"
''
