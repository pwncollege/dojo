{ pkgs }:

let
  initScript = pkgs.writeScript "dojo-init" ''
    #!${pkgs.bash}/bin/bash

    DEFAULT_PROFILE="/nix/var/nix/profiles/default"

    export PATH="$DEFAULT_PROFILE/bin:$PATH"
    export SSL_CERT_FILE="$DEFAULT_PROFILE/etc/ssl/certs/ca-bundle.crt"
    export MANPATH="$DEFAULT_PROFILE/share/man:$MANPATH"

    mkdir -pm 1777 /run/dojo
    echo $DOJO_AUTH_TOKEN > /run/dojo/auth_token

    mkdir -p /run/current-system
    ln -sfT $DEFAULT_PROFILE /run/current-system/sw

    exec "$@"
  '';

in pkgs.stdenv.mkDerivation {
  name = "init";
  buildInputs = [ pkgs.bash ];
  dontUnpack = true;

  installPhase = ''
    runHook preInstall
    mkdir -p $out/bin
    cp ${initScript} $out/bin/dojo-init
    runHook postInstall
  '';
}
