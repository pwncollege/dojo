{ pkgs }:

let
  pythonEnv = pkgs.python3.withPackages (ps: with ps; [
    ipython
    requests
    flask
    pwntools
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
  ] ++ (import ../vm/windows { inherit pkgs; });
}
