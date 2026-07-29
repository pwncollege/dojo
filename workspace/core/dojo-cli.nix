{ pkgs }:

let
  python = pkgs.python3.withPackages (ps: [ ps.requests, ps.textual ]);
in
pkgs.writeShellScriptBin "dojo" ''
  exec ${python}/bin/python3 ${./dojo-cli.py} "$@"
''
