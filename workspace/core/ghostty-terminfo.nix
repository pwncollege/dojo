{ pkgs }:

# Ghostty uses xterm-ghostty, while ncurses 6.6 installs this entry only as ghostty.
pkgs.runCommand "ghostty-terminfo" { } ''
  mkdir -p $out/share/terminfo/x
  ln -s ${pkgs.ncurses}/share/terminfo/g/ghostty $out/share/terminfo/x/xterm-ghostty
''
