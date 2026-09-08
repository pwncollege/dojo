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
  sources = {
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
    };
  };
  metadata = pkgs.writeText "documentation-sources.json" (
    builtins.toJSON (pkgs.lib.mapAttrs (_: source: { inherit (source) version url; }) sources)
  );
  index = pkgs.writeText "documentation-index.html" ''
    <!doctype html><html lang="en"><head><meta charset="utf-8"><title>Offline documentation</title></head><body>
    <h1>Offline documentation</h1><ul>
    ${pkgs.lib.concatStringsSep "\n" (
      pkgs.lib.mapAttrsToList (name: source: ''
        <li><a href="${name}/index.html">${name}</a> (${source.version})</li>
      '') sources
    )}
    </ul><p>Read with w3m or the workspace browser. Some links and interactive examples require network access.</p>
    <p>In w3m: Tab selects the next link, Enter follows it, B goes back, / searches this page, q quits.</p>
    </body></html>
  '';
in
pkgs.runCommand "dojo-offline-documentation"
  {
    nativeBuildInputs = [ pkgs.rsync ];
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
    mkdir -p "$out/share/doc"
    ${pkgs.lib.concatStringsSep "\n" (
      pkgs.lib.mapAttrsToList (name: source: ''
        mkdir -p "$out/share/doc/${name}"
        rsync -r --chmod=Du+w --exclude=.doctrees ${source.path}/ "$out/share/doc/${name}/"
        ${pkgs.lib.optionalString (source ? license) ''
          cp ${source.license} "$out/share/doc/${name}/LICENSE"
        ''}
      '') sources
    )}
    cp ${index} "$out/share/doc/index.html"
    cp ${metadata} "$out/share/doc/sources.json"
  ''
