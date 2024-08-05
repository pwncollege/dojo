{ pkgs }:

pkgs.stdenv.mkDerivation {
  name = "ssh-entrypoint";
  propagatedBuildInputs = with pkgs; [ bashInteractive ];
  dontUnpack = true;

  installPhase = ''
    runHook preInstall
    mkdir -p $out/bin
    ln -s ${pkgs.bashInteractive}/bin/bash $out/bin/ssh-entrypoint
    runHook postInstall
  '';
}
