{ pkgs }:

let
  execSuid = pkgs.rustPlatform.buildRustPackage rec {
    pname = "exec-suid";
    version = "0.1.3";

    src = pkgs.fetchFromGitHub {
      owner = "pwncollege";
      repo = "exec-suid";
      rev = "d9d518a221cb3689558b2e62f0b7102d9efd2686";
      sha256 = "sha256-Q1wVBR7ys8BeUyXinMn/D1QMTmwPwLMNZmOErETf6/8=";
    };

    cargoHash = "sha256-VWlQ7ODc74rWNo5dNaOlHoQDDbQgfWqvn72Ca9D+tko=";

    meta = with pkgs.lib; {
      description = "A simple interface for running scripts as suid";
      license = licenses.bsd2;
      platforms = platforms.linux;
      suid = [ "bin/exec-suid" ];
    };
  };
in

pkgs.stdenv.mkDerivation {
  name = "sudo";
  src = ./sudo.py;

  buildInputs = [ execSuid pkgs.python3 ];

  unpackPhase = ''
    runHook preUnpack
    cp $src $PWD
    runHook postUnpack
  '';

  installPhase = ''
    runHook preInstall
    mkdir -p $out/bin
    echo "#!${execSuid}/bin/exec-suid -- ${pkgs.python3}/bin/python3" > $out/bin/sudo
    cat ${./sudo.py} >> $out/bin/sudo
    chmod +x $out/bin/sudo
    runHook postInstall
  '';

  meta = with pkgs.lib; {
    description = "A simple sudo implementation";
    license = licenses.bsd2;
    platforms = platforms.linux;
    suid = [ "bin/sudo" ];
  };
}
