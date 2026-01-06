{ pkgs }:

in pkgs.stdenv.mkDerivation {
  name = "dojo";
  src = ./dojo-cli.py;

  buildInputs = [ pkgs.python3 ];

  unpackPhase = ''
    runHook preUnpack
    cp $src $PWD
    runHook postUnpack
  '';

  installPhase = ''
    runHook preInstall
    mkdir -p $out/bin
    echo "#!${pkgs.python3}/bin/python3" > $out/bin/dojo
    cat ${./dojo-cli.py} >> $out/bin/dojo
    chmod +x $out/bin/dojo
    runHook postInstall
  '';

  meta = with pkgs.lib; {
    description = "CLI application to interact with the pwncollege dojo.";
    platforms = platforms.linux;
  };
}
