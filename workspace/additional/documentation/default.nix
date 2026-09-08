{ pkgs }:

let
  mdn = import ./mdn.nix { inherit pkgs; };
  flask = import ./sphinx.nix {
    inherit pkgs;
    package = pkgs.python3Packages.flask;
  };
  requests = import ./sphinx.nix {
    inherit pkgs;
    package = pkgs.python3Packages.requests;
  };
  pwntools = import ./pwntools.nix { inherit pkgs; };
  python = pkgs.python3.withPackages (ps: [
    ps.beautifulsoup4
    ps.lxml
  ]);
  sources = pkgs.writeText "documentation-sources.json" (
    builtins.toJSON {
      python = {
        path = "${pkgs.python3.doc}/share/doc/python${pkgs.python3.pythonVersion}-${pkgs.python3.version}/html";
        version = pkgs.python3.version;
        url = "https://docs.python.org/${pkgs.python3.pythonVersion}/";
      };
      sqlite = {
        path = "${pkgs.sqlite.doc}/share/doc/sqlite";
        version = pkgs.sqlite.version;
        url = "https://www.sqlite.org/";
      };
      flask = {
        path = "${flask}/html";
        version = flask.version;
        url = "https://flask.palletsprojects.com/en/stable/";
        license = "${flask}/LICENSE";
      };
      requests = {
        path = "${requests}/html";
        version = requests.version;
        url = "https://requests.readthedocs.io/en/latest/";
        license = "${requests}/LICENSE";
      };
      pwntools = {
        path = "${pwntools}/html";
        version = pwntools.version;
        url = "https://docs.pwntools.com/en/stable/";
        license = "${pwntools}/LICENSE";
      };
      mdn = {
        path = "${mdn}/html";
        version = mdn.version;
        url = "https://developer.mozilla.org/";
        prefix = "developer.mozilla.org";
      };
    }
  );
in
pkgs.runCommand "dojo-offline-documentation"
  {
    nativeBuildInputs = [
      python
      pkgs.w3m
    ];
    passthru = {
      inherit
        mdn
        flask
        requests
        pwntools
        ;
    };
  }
  ''
    python ${./prepare.py} ${sources} "$out/share/doc"
  ''
