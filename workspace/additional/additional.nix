{ pkgs }:

let
  bata24-gef = import ./bata24-gef.nix { inherit pkgs; };
  burpsuite = import ./burpsuite.nix { inherit pkgs; };
  ghidra = import ./ghidra.nix { inherit pkgs; };
  wireshark = import ./wireshark.nix { inherit pkgs; };

  pythonPackages = ps: with ps; [
    angr
    asteval
    flask
    ipython
    jupyter
    pillow
    psutil
    pwntools
    pycryptodome
    pyroute2
    r2pipe
    requests
    ropper
    scapy
    selenium
  ];

  pythonEnv = pkgs.angrPkgs.python3.withPackages pythonPackages;

  tools = with pkgs; {
    build = [ (lib.lowPrio clang) clang-tools cmake (lib.hiPrio gcc) gnumake qemu rustup ];

    cli-tools = [ atuin bat delta hexyl hyperfine navi sd zoxide ];

    compress = [ gnutar gzip unzip zip ];

    debug = [ bata24-gef gdb gef ltrace pwndbg strace ];

    editor = [ emacs gedit nano neovim vim zed-editor.remote_server ];

    exploit = [ aflplusplus rappel ropgadget sage ];

    fetch = [ fastfetch neofetch ];

    finder = [ broot dust eza fd fzf ripgrep ripgrep-all ];

    lsp = [ ruff ty ];

    network = [ burpsuite netcat-openbsd nmap tcpdump termshark tshark wireshark ];

    reverse = [ angr-management binaryninja-free cutter file ghidra ida-free radare2 ];

    shells = [ fish nushell oh-my-zsh starship zsh ];

    system = [ bottom firejail htop landrun ncdu nftables openssh rsync ];

    terminal = [ ghostty.terminfo kitty.terminfo screen tmux zellij ];

    web = [ firefox geckodriver ];
  };

in
{
  packages = with pkgs;
    [ (lib.hiPrio pythonEnv) ]
    ++ tools.build
    ++ tools.cli-tools
    ++ tools.compress
    ++ tools.debug
    ++ tools.editor
    ++ tools.exploit
    ++ tools.fetch
    ++ tools.finder
    ++ tools.lsp
    ++ tools.network
    ++ tools.reverse
    ++ tools.shells
    ++ tools.system
    ++ tools.terminal
    ++ tools.web;
}
