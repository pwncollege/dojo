{ pkgs }:

pkgs.rustPlatform.buildRustPackage rec {
  pname = "exec-suid";
  version = "0.1.5";

  src = pkgs.fetchFromGitHub {
    owner = "pwncollege";
    repo = pname;
    rev = "v${version}";
    sha256 = "sha256-k9d6NbgnkbJXF9Eefh/CaM4GrsMNO9UtIBMp8U5AAwM=";
  };

  cargoLock = {
    lockFile = "${src}/Cargo.lock";
  };

  meta = with pkgs.lib; {
    description = "A simple interface for running scripts as suid";
    license = licenses.bsd2;
    platforms = platforms.linux;
    suid = [ "bin/exec-suid" ];
  };
}
