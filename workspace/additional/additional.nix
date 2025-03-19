{ pkgs }:

let
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
    build = [ gcc gnumake cmake qemu ];

    compression = [ zip unzip gzip gnutar ];

    system = [ htop rsync openssh nftables ];

    editors = [ vim neovim emacs ];

    terminal = [ tmux screen ];

    network = [ netcat-openbsd tcpdump wireshark termshark nmap burpsuite ];

    debugging = [ strace ltrace gdb pwndbg gef ];

    reversing = [ ghidra ida-free radare2 cutter angr-management binaryninja-free ];

    web = [ firefox geckodriver ];

    exploitation = [ aflplusplus rappel ropgadget sage ];
  };

in
{
  packages = with pkgs;
    [ (lib.hiPrio pythonEnv) ]
    ++ tools.build
    ++ tools.compression
    ++ tools.system
    ++ tools.editors
    ++ tools.terminal
    ++ tools.network
    ++ tools.debugging
    ++ tools.reversing
    ++ tools.web
    ++ tools.exploitation;
}
