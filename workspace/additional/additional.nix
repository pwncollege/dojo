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
    ropper
    scapy
    selenium
  ]);

in
{
  packages = with pkgs; [
    (lib.hiPrio pythonEnv)

    gcc
    gnumake

    qemu

    strace
    gdb
    pwndbg
    gef
    openssh
    netcat-openbsd

    vim
    emacs

    ghidra
    ida-free
    radare2
    # TODO: angr-management
    # TODO: binary-ninja

    wireshark
    nmap
    tcpdump
    firefox
    geckodriver
    burpsuite

    aflplusplus
    rappel
    ropgadget
    # TODO: rp++

    sage

    # TODO: apt-tools
  ];
}
