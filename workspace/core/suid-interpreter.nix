{ pkgs }:

let
  buildSuid = name: flag: ''
    ${pkgs.stdenv.mkDerivation {
      name = name;
      src = ./suid_interpreter.c;
      buildInputs = [ pkgs.gcc ];

      unpackPhase = ''
        runHook preUnpack
        cp $src $PWD
        runHook postUnpack
      '';

      buildPhase = ''
        runHook preBuild
        gcc $src -D${flag} -o ${name}
        runHook postBuild
      '';

      installPhase = ''
        runHook preInstall
        mkdir -p $out/bin
        cp ${name} $out/bin/
        runHook postInstall
      '';
    }}
  '';

in pkgs.symlinkJoin {
  name = "suid-interpreter";
  paths = with pkgs; [
    (buildSuid "python-dojo-suid" "SUID_PYTHON_DOJO")
    (buildSuid "python-suid" "SUID_PYTHON")
    (buildSuid "bash-suid" "SUID_BASH")
    (buildSuid "sh-suid" "SUID_SH")
  ];
}
