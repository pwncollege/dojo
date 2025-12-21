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

  pythonEnv = pkgs.python3.withPackages pythonPackages;

  tools = with pkgs; {
    build = [ (lib.lowPrio clang) clang-tools cmake (lib.hiPrio gcc) gnumake qemu rustup ];

    compress = [ gnutar gzip unzip zip ];

    debug = [ bata24-gef gdb gef ltrace pwndbg strace ];

    editor = [ emacs gedit nano neovim vim zed-editor.remote_server ];

    exploit = [ aflplusplus rappel ropgadget sage ];

    lsp = [ ruff ty ];

    network = [ burpsuite netcat-openbsd nmap tcpdump termshark tshark wireshark ];

    reverse = [ angr-management binaryninja-free cutter file ghidra ida-free radare2 ];

    shells = [ fish nushell zsh ];

    shell-tools = [ atuin bat fd fzf oh-my-zsh starship zoxide ripgrep ];

    system = [ firejail htop landrun nftables openssh rsync ];

    terminal = [ kitty.terminfo screen tmux ];

    web = [ firefox geckodriver ];
  };

in
{
  packages = with pkgs;
    [ (lib.hiPrio pythonEnv) ]
    ++ tools.build
    ++ tools.compress
    ++ tools.debug
    ++ tools.editor
    ++ tools.exploit
    ++ tools.lsp
    ++ tools.network
    ++ tools.reverse
    ++ tools.shells
    ++ tools.shell-tools
    ++ tools.system
    ++ tools.terminal
    ++ tools.web;
}
