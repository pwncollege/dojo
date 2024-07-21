{ pkgs }:

let

in pkgs.stdenv.mkDerivation {
  name = "service";
  src = ./service.py;

  buildInputs = [ pkgs.python3 ];

  unpackPhase = ''
    runHook preUnpack
    cp $src $PWD
    runHook postUnpack
  '';

  installPhase = ''
    runHook preInstall
    mkdir -p $out/bin
    echo "#!${pkgs.python3.interpreter}" > $out/bin/service
    cat ${./service.py} >> $out/bin/service
    chmod +x $out/bin/service
    runHook postInstall
  '';
}
