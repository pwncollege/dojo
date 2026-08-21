{ pkgs }:

let
  inherit (pkgs.ghidra) pname version meta;

  description = "Software reverse engineering (SRE) suite of tools developed by NSA's Research Directorate in support of the Cybersecurity mission";

  pythonEnv = pkgs.python3.withPackages (ps: [
    ps.protobuf
    ps.psutil
  ]);

  gdb = pkgs.symlinkJoin {
    name = "ghidra-gdb";
    paths = [ pkgs.gdb ];
    nativeBuildInputs = [ pkgs.makeWrapper ];
    postBuild = ''
      wrapProgram $out/bin/gdb \
        --suffix PYTHONPATH : "${pythonEnv}/${pkgs.python3.sitePackages}"
    '';
  };

in
pkgs.stdenv.mkDerivation {
  inherit
    pname
    version
    meta
    description
    ;

  src = pkgs.ghidra;

  buildInputs = [ pkgs.makeWrapper ];

  doCheck = true;

  checkPhase = ''
    runHook preCheck
    export PYTHONPATH="${pkgs.ghidra}/lib/ghidra/Ghidra/Debug/Debugger-agent-gdb/pypkg/src:${pkgs.ghidra}/lib/ghidra/Ghidra/Debug/Debugger-rmi-trace/pypkg/src"
    ${gdb}/bin/gdb -q -nx -batch \
      -ex 'python import google.protobuf, psutil, ghidragdb.commands' \
      -ex 'help ghidra trace connect' | \
      ${pkgs.gnugrep}/bin/grep -F 'Connect GDB to Ghidra for tracing.'
    runHook postCheck
  '';

  installPhase = ''
    runHook preInstall

    mkdir -p "$out/bin"

    # Ghidra will spam-log stack traces into the home directory when not run in a desktop environment.
    makeWrapper "$src/bin/ghidra" \
      "$out/bin/ghidra" \
      --prefix PATH : "${pkgs.lib.makeBinPath [ gdb ]}" \
      --run 'if [ -z "$DISPLAY" ]; then echo "Error: DISPLAY is not set. Please run under desktop environment." >&2; exit 1; fi'

    cp -r "$src/share" "$out/share"

    runHook postInstall
  '';
}
