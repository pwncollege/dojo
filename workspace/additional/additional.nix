{ pkgs }:

let
  pythonEnv = pkgs.python3.withPackages (ps: with ps; [
    angr
    asteval
    flask
    ipython
    jupyter
    psutil
    pwntools
    pycryptodome
    r2pipe
    requests
    scapy
    selenium
  ]);
in
{
  packages = with pkgs; [
    pythonEnv

    qemu

    gdb
    pwndbg
    gef

    ghidra
    ida-free
    radare2

    wireshark
    nmap
    tcpdump
  ];
}
