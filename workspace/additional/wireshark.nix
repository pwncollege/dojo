{ pkgs }:

# in kata containers wireshark hangs becuase of a bad icon theme in /usr/share/icons/hicolor 

let
  inherit (pkgs.wireshark) pname version meta;

  description = "Network protocol analyzer";

in pkgs.stdenv.mkDerivation {
  inherit pname version meta description;

  src = pkgs.wireshark;

  buildInputs = [ pkgs.makeWrapper ];

  installPhase = ''
      runHook preInstall

      mkdir -p "$out/bin"
      makeWrapper "$src/bin/wireshark" \
        "$out/bin/wireshark" \
        --set XDG_DATA_DIRS ""

      cp -r "$src/share" "$out/share"

      runHook postInstall
  '';
}


