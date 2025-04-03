{ pkgs }:

# ghidra will spam-log stack traces into the home directory when not run in a desktop environment

let
  inherit (pkgs.ghidra) pname version meta;

  description = "Software reverse engineering (SRE) suite of tools developed by NSA's Research Directorate in support of the Cybersecurity mission";

in pkgs.stdenv.mkDerivation {
  inherit pname version meta description;

  src = pkgs.ghidra;

  buildInputs = [ pkgs.makeWrapper ];

  installPhase = ''
      runHook preInstall

      mkdir -p "$out/bin"
      makeWrapper "$src/bin/ghidra" \
        "$out/bin/ghidra" \
        --run 'if [ -z "$DISPLAY" ]; then echo "Error: DISPLAY is not set. Please run under desktop environment." >&2; exit 1; fi'

      cp -r "$src/share" "$out/share"

      runHook postInstall
  '';
}
