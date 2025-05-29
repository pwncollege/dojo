{ pkgs
, gdb ? pkgs.gdb
, python3 ? pkgs.python3
}:

let
  lib = pkgs.lib;
  pythonPath =
    with python3.pkgs;
    makePythonPath [
      keystone-engine
      unicorn
      capstone
      ropper
  ];
in
python3.pkgs.buildPythonPackage rec {
  pname = "bata24-gef";
  version = "unstable-2025-05-28";

  src = pkgs.fetchFromGitHub {
    owner = "bata24";
    repo = "gef";
    rev = "4d7dc1d9a5a407aea3935622150aeea1fcf355dc";
    sha256 = "sha256-xlTIQ0VbktdYHT4JRK6HzoKKT7WzKqqPS0aTbpvBMV0=";
  };

  format = "other";

  nativeBuildInputs = [ pkgs.makeWrapper ];

  installPhase = ''
    mkdir -p $out/share/bata24-gef
    cp gef.py $out/share/bata24-gef
    makeWrapper ${gdb}/bin/gdb $out/bin/bata24-gef \
      --add-flags "-q -x $out/share/bata24-gef/gef.py" \
      --set NIX_PYTHONPATH ${pythonPath} \
      --prefix PATH : ${
        lib.makeBinPath [
          pkgs.gdb
          python3
          pkgs.bintools-unwrapped
          pkgs.file
          pkgs.ps
        ]
      }
  '';

  meta = with lib; {
    description = "GDB Enhanced Features fork by bata24";
    mainProgram = "bata24-gef";
    platforms = platforms.all;
    homepage = "https://github.com/bata24/gef";
    license = licenses.mit;
    maintainers = with maintainers; [ ];
  };
}
