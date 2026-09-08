{ pkgs }:

let
  autoprogram = pkgs.python3Packages.buildPythonPackage rec {
    pname = "sphinxcontrib-autoprogram";
    version = "0.1.5";
    pyproject = true;
    src = pkgs.fetchPypi {
      inherit pname version;
      hash = "sha256-fsa98jW0kdxpPRpy+3+fc022nim4EzNDXvtB8J+bvu8=";
    };
    build-system = [ pkgs.python3Packages.setuptools ];
    dependencies = with pkgs.python3Packages; [
      sphinx
      six
    ];
    doCheck = false;
    pythonImportsCheck = [ "sphinxcontrib.autoprogram" ];
  };
in
(import ./sphinx.nix {
  inherit pkgs;
  package = pkgs.python3Packages.pwntools;
  sourceDir = "docs/source";
  extraPackages = [ autoprogram ];
}).overrideAttrs
  {
    postPatch = ''
      substituteInPlace pwnlib/util/packing.py --replace-fail ':function:' ':func:'
    '';
    preBuild = ''
      export PYTHONPATH="$PWD"
    '';
  }
