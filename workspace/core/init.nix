{ pkgs }:

let
  initScript = pkgs.writeScript "dojo-init" ''
    #!${pkgs.bash}/bin/bash

    IMAGE_PATH="$(echo $PATH | cut -d: -f3-)"
    DEFAULT_PROFILE="/nix/var/nix/profiles/default"

    export PATH="$DEFAULT_PROFILE/bin:$PATH"
    export SSL_CERT_FILE="$DEFAULT_PROFILE/etc/ssl/certs/ca-bundle.crt"
    export MANPATH="$DEFAULT_PROFILE/share/man:$MANPATH"

    mkdir -p /run/current-system
    ln -sfT $DEFAULT_PROFILE /run/current-system/sw

    mkdir -p /run/dojo
    for path in /run/current-system/sw/*; do
      ln -sfT $path /run/dojo/$(basename $path)
    done

    mkdir -pm 1777 /run/dojo/var /tmp
    mkdir /run/dojo/var/root

    if [ ! -e /run/challenge/bin ]; then
      mkdir -p /run/challenge && ln -sfT /challenge/bin /run/challenge/bin
    fi

    if [ ! -e /bin/sh ]; then
      mkdir -p /bin && ln -sfT /run/dojo/bin/sh /bin/sh
    fi

    mkdir -p /home/hacker /root
    mkdir -p /etc && touch /etc/passwd /etc/group
    echo "root:x:0:0:root:/root:/run/dojo/bin/bash" >> /etc/passwd
    echo "hacker:x:1000:1000:hacker:/home/hacker:/run/dojo/bin/bash" >> /etc/passwd
    echo "sshd:x:112:65534::/run/sshd:/usr/sbin/nologin" >> /etc/passwd
    echo "root:x:0:" >> /etc/group
    echo "hacker:x:1000:" >> /etc/group

    echo "PATH=\"/run/challenge/bin:/run/workspace/bin:$IMAGE_PATH\"" > /etc/environment

    echo $DOJO_AUTH_TOKEN > /run/dojo/var/auth_token

    read DOJO_FLAG
    echo $DOJO_FLAG | install -m 400 /dev/stdin /flag

    exec > /run/dojo/var/root/init.log 2>&1
    chmod 600 /run/dojo/var/root/init.log

    if [ "$DOJO_MODE" = "privileged" ]; then
      touch /run/dojo/var/root/privileged
    fi

    if [ -x "/challenge/.init" ]; then
        PATH="/run/challenge/bin:$IMAGE_PATH" /challenge/.init
    fi

    touch /run/dojo/var/ready

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
