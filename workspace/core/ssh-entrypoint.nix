{ pkgs }:

let
  sshEntryPoint = pkgs.writeScript "ssh-entrypoint" ''
    #!${pkgs.bashInteractive}/bin/bash

    if [ "$#" -gt 0 ]; then
      $SHELL "$@"
    else
      $SHELL --login
    fi

    exit $?
  '';

in pkgs.stdenv.mkDerivation {
  name = "ssh-entrypoint";
  propagatedBuildInputs = with pkgs; [ bashInteractive ];
  dontUnpack = true;

  installPhase = ''
    runHook preInstall
    mkdir -p $out/bin
    cp ${sshEntryPoint} $out/bin/ssh-entrypoint
    runHook postInstall
  '';
}
