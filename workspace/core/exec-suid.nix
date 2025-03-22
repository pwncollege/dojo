{ pkgs }:

pkgs.rustPlatform.buildRustPackage rec {
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
}
