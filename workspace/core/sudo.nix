{ pkgs }:

let
  exec-suid = import ./exec-suid.nix { inherit pkgs; };

in pkgs.stdenv.mkDerivation {
  name = "sudo";
  src = ./sudo.py;

  buildInputs = [ exec-suid pkgs.python3 ];

  unpackPhase = ''
    runHook preUnpack
    cp $src $PWD
    runHook postUnpack
  '';

  installPhase = ''
    runHook preInstall
    mkdir -p $out/bin
    echo "#!${exec-suid}/bin/exec-suid -- ${pkgs.python3}/bin/python3" > $out/bin/sudo
    cat ${./sudo.py} >> $out/bin/sudo
    chmod +x $out/bin/sudo
    runHook postInstall
  '';

  meta = with pkgs.lib; {
    description = "A simple sudo implementation";
    license = licenses.bsd2;
    platforms = platforms.linux;
    suid = [ "bin/sudo" ];
  };
}
