{ pkgs ? import <nixpkgs> {} }:
with pkgs;

mkShell {

  # Riggrep patch requires python
  nativeBuildInputs = [ python312 novnc tigervnc python312Packages.websockify xterm fluxbox busybox ];
  shellHook = ''
  ln -s $(which novnc) /nix/bin/novnc
  ln -s $(which Xvnc) /nix/bin/tigervnc
  ln -s $(which vncpasswd) /nix/bin/tigervncpasswd
  ln -s $(which websockify) /nix/bin/websockify
  ln -s $(which xterm) /nix/bin/xterm
  ln -s $(which fluxbox) /nix/bin/fluxbox
  ln -s $(which start-stop-daemon) /nix/bin/start-stop-daemon
  '';
}
