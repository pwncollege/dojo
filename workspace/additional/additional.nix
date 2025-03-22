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

  # burpsuite is packaged in a "buildFHSEnv" environment, which will not work in a container due to attempting to mount
  # it seems to work just fine without the "buildFHSUserEnv" environment
  # additionally, avoid burpsuite dumping ~500MB of data into the home directory
  burpsuite = let
    extraFlags = "--disable-auto-update --data-dir=\\\${TMPDIR:-/tmp}/.BurpSuite";
  in pkgs.stdenv.mkDerivation {
    inherit (pkgs.burpsuite) pname version description desktopItem meta;
    src = pkgs.burpsuite;
    buildInputs = [ pkgs.makeWrapper ];
    installPhase = ''
      runHook preInstall
      initPath="$(sed -nE 's/.*--symlink ([^ ]*) \/init.*/\1/p' "$src/bin/burpsuite")"
      if [ -z "$initPath" ]; then
        echo "Error: Could not extract init script from burpsuite launcher" >&2
        exit 1
      fi
      mkdir -p "$out/bin"
      makeWrapper "$initPath" "$out/bin/burpsuite" --add-flags "${extraFlags}"
      runHook postInstall
    '';
  };

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
