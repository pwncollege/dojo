# Ghidra extension can be in pkgs/tools/security/ghidra/extensions/decomp2dbg/default.nix
{ lib
, stdenv
, fetchurl
, buildGhidraExtension
, ghidra
}:

let
  version = "3.9.6";
in
buildGhidraExtension {
  pname = "decomp2dbg";
  inherit version;

  src = fetchurl {
    url = "https://github.com/mahaloz/decomp2dbg/releases/download/v${version}/d2d-ghidra-plugin.zip";
    sha256 = "2b024a7464284775529463721c922d1a6f7bd38a7c3a654717ad37e516117498"; 
  };

  dontUnpack = true;

  installPhase = ''
    runHook preInstall

    mkdir -p $out/lib/ghidra/Ghidra/Extensions
    cp $src $out/lib/ghidra/Ghidra/Extensions/

    runHook postInstall
  '';

  meta = with lib; {
    description = "Ghidra extension for GDB integration via decomp2dbg";
    homepage = "https://github.com/mahaloz/decomp2dbg";
    license = licenses.bsd2;
    maintainers = with maintainers; [ ];
  };
}