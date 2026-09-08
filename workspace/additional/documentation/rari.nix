{ pkgs }:

pkgs.rustPlatform.buildRustPackage {
  pname = "rari-offline";
  version = "0.2.34";

  src = pkgs.fetchFromGitHub {
    owner = "mdn";
    repo = "rari";
    tag = "v0.2.34";
    hash = "sha256-Yom6FjEormuomHtGKvfvJ378/h3f6eCKvfHwCVCm8LE=";
  };

  cargoHash = "sha256-iVaa2lvLtJ3p/1xrPvV015b54SBCoLawEjdSaVJAdkI=";
  cargoBuildFlags = [
    "-p"
    "rari"
    "--ignore-rust-version"
  ];
  doCheck = false;
  buildInputs = [ pkgs.openssl ];

  postPatch = ''
    python3 ${./patch-rari.py}
  '';

  nativeBuildInputs = [
    pkgs.pkg-config
    pkgs.python3
  ];
}
