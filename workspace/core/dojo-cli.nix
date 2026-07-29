{ pkgs }:

let
  python = pkgs.python3.withPackages (ps: [ ps.requests ps.textual ps.itsdangerous ]);
  cli = pkgs.runCommand "dojo-cli-src" {} ''
    mkdir -p $out
    cp ${./dojo-cli.py} $out/dojo-cli.py
    cp ${./tui.py} $out/tui.py
  '';
in
pkgs.writeShellScriptBin "dojo" ''
  exec ${python}/bin/python3 ${cli}/dojo-cli.py "$@"
''
