{ pkgs }:

pkgs.stdenv.mkDerivation {
  name = "sudo";
  src = ./sudo.py;

  unpackPhase = ''
    runHook preUnpack
    cp $src $PWD
    runHook postUnpack
  '';

  installPhase = ''
    runHook preInstall
    mkdir -p $out/bin
    echo "#!/usr/bin/env python-dojo-suid" > $out/bin/sudo
    cat ${./sudo.py} >> $out/bin/sudo
    chmod +x $out/bin/sudo
    runHook postInstall
  '';
}
