{ pkgs }:

let
  wrapper = client: executable: pkgs.writeShellScriptBin client ''
    exec ${pkgs.python3}/bin/python3 ${./llm-wrapper.py} ${client} ${executable} "$@"
  '';
in
pkgs.symlinkJoin {
  name = "dojo-llm-tools";
  paths = [
    (wrapper "claude" "${pkgs.claude-code}/bin/claude")
    (wrapper "codex" "${pkgs.codex}/bin/codex")
    (wrapper "opencode" "${pkgs.opencode}/bin/opencode")
  ];
}
