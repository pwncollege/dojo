{ pkgs }:

let
  initScript = pkgs.writeScript "dojo-init" ''
    #!${pkgs.bash}/bin/bash

    set -o pipefail

    FULL_PATH="$PATH"
    IMAGE_PATH="$(echo $PATH | cut -d: -f3-)"
    DEFAULT_PROFILE="/nix/var/nix/profiles/dojo-workspace"
    PATH="$DEFAULT_PROFILE/bin"

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

    home_directory="/home/hacker"
    home_mount_options="$(findmnt -nro OPTIONS -- "$home_directory")"
    if [ -n "$home_mount_options" ] && ! printf '%s' "$home_mount_options" | grep -Fqw 'nosuid'; then
      mount -o remount,nosuid "$home_directory" || {
        echo "DOJO_INIT_FAILED:Failed to remount home '$home_directory' with nosuid option." >&2
        exit 1
      }
    fi

    mkdir -p /home/hacker /root
    mkdir -p /etc /etc/profile.d && touch /etc/passwd /etc/group
    echo "root:x:0:0:root:/root:/run/dojo/bin/bash" >> /etc/passwd
    echo "hacker:x:1000:1000:hacker:/home/hacker:/run/dojo/bin/bash" >> /etc/passwd
    echo "sshd:x:112:65534::/run/sshd:/usr/sbin/nologin" >> /etc/passwd
    echo "root:x:0:" >> /etc/group
    echo "hacker:x:1000:" >> /etc/group
    echo "PATH=\"$FULL_PATH\"" > /etc/environment
    ln -sfT /run/dojo/etc/profile.d/99-dojo-workspace.sh /etc/profile.d/99-dojo-workspace.sh

    mkdir -p /etc/gdb/gdbinit.d
    echo "set debug-file-directory /lib/debug" > /etc/gdb/gdbinit.d/dojo.gdb

    echo $DOJO_AUTH_TOKEN > /run/dojo/var/auth_token

    echo "DOJO_INIT_INITIALIZED"

    if ! read -t 5 DOJO_FLAG; then
      echo "DOJO_INIT_FAILED:Flag initialization error."
      exit 1
    fi
    echo $DOJO_FLAG | install -m 400 /dev/stdin /flag

    for path in /home/hacker /home/hacker/.config; do
      test -L "$path" && rm -f "$path"
      mkdir -p "$path" && chown 1000:1000 "$path" && chmod 755 "$path"
    done

    if [ -x "/challenge/.init" ]; then
      (
        touch /run/dojo/var/root/init.log
        chmod 600 /run/dojo/var/root/init.log
        PATH="/run/challenge/bin:$IMAGE_PATH" "$DEFAULT_PROFILE"/bin/timeout -k 10 30 /challenge/.init >& /run/dojo/var/root/init.log &
        INIT_PID=$!
        tail -f /run/dojo/var/root/init.log --pid "$INIT_PID" | head -n1M
        if ! wait "$INIT_PID"
        then
          echo "DOJO_INIT_FAILED:Challenge initialization error."
          exit 1
        fi
      )
    fi

    touch /run/dojo/var/ready
    echo "DOJO_INIT_READY"

    exec "$@"
  '';

  profile = pkgs.writeText "dojo-profile" ''
    if [[ "$PATH" != "/run/challenge/bin:/run/dojo/bin:"* ]]; then
      export PATH="/run/challenge/bin:/run/dojo/bin:$PATH"
    fi

    if [[ -z "$LANG" ]]; then
      export LANG="C.UTF-8"
    fi

    if [[ -z "$MANPATH" ]]; then
      # "If the value of $MANPATH ends with a colon, then the default search path is added at its end."
      export MANPATH="/run/dojo/share/man:"
    fi

    if [[ -z "$SSL_CERT_FILE" ]]; then
      export SSL_CERT_FILE="/run/dojo/etc/ssl/certs/ca-bundle.crt"
    fi

    if [[ -z "$TERMINFO" ]]; then
      export TERMINFO="/run/dojo/share/terminfo"
    fi

    if tput setaf 1 &> /dev/null; then
      # Terminal supports colors
      PS1='\[\033[01;32m\]\u@\h\[\033[00m\]:\[\033[01;34m\]\w\[\033[00m\]\$ '
      alias ls='ls --color=auto'
      alias grep='grep --color=auto'
    fi

    if [[ "$TERM" == xterm* ]]; then
      # Set the terminal title to the current user and host
      PS1="\[\e]0;\u@\h: \w\a\]$PS1"
    fi

    PROMPT_COMMAND="history -a; $PROMPT_COMMAND"
  '';

in pkgs.stdenv.mkDerivation {
  name = "init";
  buildInputs = [ pkgs.bash ];
  dontUnpack = true;

  installPhase = ''
    runHook preInstall
    mkdir -p $out/bin $out/etc/profile.d
    cp ${initScript} $out/bin/dojo-init
    cp ${profile} $out/etc/profile.d/99-dojo-workspace.sh
    runHook postInstall
  '';
}
