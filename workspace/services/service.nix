{ pkgs }:

pkgs.stdenv.mkDerivation {
  name = "dojo-service";
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
    echo "#!${pkgs.python3.interpreter}" > $out/bin/dojo-service
    cat ${./service.py} >> $out/bin/dojo-service
    chmod +x $out/bin/dojo-service
    runHook postInstall
  '';
}
