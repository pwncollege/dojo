{ pkgs }:

pkgs.rustPlatform.buildRustPackage rec {
  pname = "exec-suid";
  version = "1.0.0";

  src = pkgs.fetchFromGitHub {
    owner = "pwncollege";
    repo = pname;
    rev = "v${version}";
    sha256 = "sha256-1VW0YUTxbrK0scULbLJEUDGMfqJBosZ8plCRZqX37UA=";
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
