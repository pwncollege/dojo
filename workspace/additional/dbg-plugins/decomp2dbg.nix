# GDB integration can be in pkgs/development/tools/debugging/decomp2dbg/default.nix
{ lib
, stdenv
, python3
, makeWrapper
, gdb
, fetchFromGitHub
}:

let
  version = "3.9.6";  # Match Ghidra extension version
  
  decomp2dbg-py = python3.pkgs.buildPythonPackage {
    pname = "decomp2dbg";
    inherit version;

    src = fetchFromGitHub {
      owner = "mahaloz";
      repo = "decomp2dbg";
      rev = "v${version}";
      sha256 = "";  # TODO: Need to add hash after first attempt
    };

    format = "setuptools";

    meta = with lib; {
      description = "A tool to integrate Ghidra's decompiler with GDB debugging";
      homepage = "https://github.com/mahaloz/decomp2dbg";
      license = licenses.bsd2;
      maintainers = with maintainers; [ ];
    };
  };
in
stdenv.mkDerivation { # Introduces `decomp2gdb`
  pname = "decomp2dbg";
  inherit version;
  format = "other";

  nativeBuildInputs = [ makeWrapper ];

  installPhase = ''
    runHook preInstall

    mkdir -p $out/share/decomp2dbg
    cat > $out/share/decomp2dbg/gdbinit <<EOF
    source ${decomp2dbg-py}/lib/python*/site-packages/d2d.py
    EOF

    makeWrapper ${gdb}/bin/gdb $out/bin/decomp2gdb \
      --set PYTHONPATH "${decomp2dbg-py}/lib/python*/site-packages:$PYTHONPATH" \
      --add-flags "-x $out/share/decomp2dbg/gdbinit"

    runHook postInstall
  '';

  meta = with lib; {
    description = "GDB and Ghidra decompiler integration";
    homepage = "https://github.com/mahaloz/decomp2dbg";
    license = licenses.bsd2;
    platforms = platforms.all;
    maintainers = with maintainers; [ ];
  };
}