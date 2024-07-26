{ pkgs }:

let
  pythonEnv = pkgs.python3.withPackages (ps: with ps; [
    ipython
    requests
    flask
    pwntools
  ]);

  linux-vm = import ../vm/linux/linux.nix { inherit pkgs service; };
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
  ] ++ linux-vm.packages;
}
