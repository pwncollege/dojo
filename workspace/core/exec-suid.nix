{ pkgs }:

pkgs.rustPlatform.buildRustPackage rec {
  pname = "exec-suid";
  version = "0.1.4";

  src = pkgs.fetchFromGitHub {
    owner = "pwncollege";
    repo = "exec-suid";
    rev = "a1d4a3579c591b7401ab2d05db0121e7244ae5e1";
    sha256 = "sha256-70OABg5zainIrpAyWxKCwep8ZsNr3YFoOQ5QgVz15YE=";
  };

  cargoHash = "sha256-BCgSjoY1xT1Dm39wL4BQaCHUcWeevF5mTnBz8DK6Pkg=";

  meta = with pkgs.lib; {
    description = "A simple interface for running scripts as suid";
    license = licenses.bsd2;
    platforms = platforms.linux;
    suid = [ "bin/exec-suid" ];
  };
}
