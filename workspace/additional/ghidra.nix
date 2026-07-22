{ pkgs }:

let
  inherit (pkgs.ghidra) pname version meta;

  description = "Software reverse engineering (SRE) suite of tools developed by NSA's Research Directorate in support of the Cybersecurity mission";

  ghidraPythonDist = "${pkgs.ghidra}/lib/ghidra/Ghidra/Debug/Debugger-rmi-trace/pypkg/dist";

  ghidraProtobuf = pkgs.python3Packages.buildPythonPackage {
    pname = "protobuf";
    version = "3.20.3";
    format = "wheel";
    src = "${ghidraPythonDist}/protobuf-3.20.3-py2.py3-none-any.whl";
    doCheck = false;
    pythonImportsCheck = [ "google.protobuf" ];
  };

  ghidraPsutil = pkgs.python3Packages.buildPythonPackage {
    pname = "psutil";
    version = "5.9.8";
    pyproject = true;
    src = "${ghidraPythonDist}/psutil-5.9.8.tar.gz";
    build-system = with pkgs.python3Packages; [
      setuptools
      wheel
    ];
    doCheck = false;
    pythonImportsCheck = [ "psutil" ];
  };

  pythonEnv = pkgs.python3.withPackages (_: [
    ghidraProtobuf
    ghidraPsutil
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

in pkgs.stdenv.mkDerivation {
  inherit pname version meta description;

  src = pkgs.ghidra;

  buildInputs = [ pkgs.makeWrapper ];

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
