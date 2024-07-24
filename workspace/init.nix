{ pkgs }:

let
  initScript = pkgs.writeScript "dojo-init" ''
    #!${pkgs.bash}/bin/bash

    DEFAULT_PROFILE="/nix/var/nix/profiles/default"

    export PATH="$DEFAULT_PROFILE/bin:$PATH"
    export SSL_CERT_FILE="$DEFAULT_PROFILE/etc/ssl/certs/ca-bundle.crt"
    export MANPATH="$DEFAULT_PROFILE/share/man:$MANPATH"

    mkdir -p /run/current-system
    ln -sfT $DEFAULT_PROFILE /run/current-system/sw

    if [ ! -e /run/challenge/bin ]; then
      mkdir -p /run/challenge && ln -sfT /challenge/bin /run/challenge/bin
    fi

    if [ ! -e /bin/sh ]; then
      mkdir -p /bin && ln -sfT $DEFAULT_PROFILE/bin/sh /bin/sh
    fi

    mkdir -p /home/hacker /root
    mkdir -p /etc && touch /etc/passwd /etc/group
    echo "root:x:0:0:root:/root:$DEFAULT_PROFILE/bin/bash" >> /etc/passwd
    echo "hacker:x:1000:1000:hacker:/home/hacker:$DEFAULT_PROFILE/bin/bash" >> /etc/passwd
    echo "root:x:0:" >> /etc/group
    echo "hacker:x:1000:" >> /etc/group
    echo "sshd:!:33:" >> /etc/group
    echo "sshd:x:71:65:SSH daemon:/var/empty:/bin/false" >> /etc/passwd


    mkdir -pm 1777 /run/dojo /tmp
    echo $DOJO_AUTH_TOKEN > /run/dojo/auth_token

    read DOJO_FLAG
    echo $DOJO_FLAG | install -m 400 /dev/stdin /flag

    # TODO: Better support privileged mode
    if [ "$DOJO_MODE" = "privileged" ] && [ -f /usr/bin/sudo ]; then
      chmod 4755 /usr/bin/sudo
      usermod -aG sudo hacker
      echo 'hacker ALL=(ALL) NOPASSWD:ALL' >> /etc/sudoers
      passwd -d root
    fi

    if [ -x "/challenge/.init" ]; then
        /challenge/.init
    fi

    touch /run/dojo/ready

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
