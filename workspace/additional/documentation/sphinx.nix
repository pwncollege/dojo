{ pkgs, package }:

let
  python = pkgs.python3.withPackages (ps: [
    package
    ps.sphinx
    ps.pallets-sphinx-themes
    ps.sphinxcontrib-log-cabinet
    ps.sphinx-tabs
    ps.myst-parser
  ]);
  config = pkgs.writeTextDir "conf.py" ''
    from pathlib import Path
    import os

    source = Path(os.environ["DOC_SOURCE"])
    exec(compile((source / "conf.py").read_text(), str(source / "conf.py"), "exec"))
    extensions += ["myst_parser"]
    language = "en"
    intersphinx_mapping = {}
    html_theme = "alabaster"
    html_theme_options = {}
    html_sidebars = {"**": ["about.html", "navigation.html", "relations.html", "searchbox.html"]}
    html_static_path = [str(source / "_static")]
    templates_path = []
    html_favicon = None
    html_logo = None
    pygments_style = "sphinx"
  '';
in
pkgs.stdenvNoCC.mkDerivation {
  pname = "${package.pname}-doc";
  inherit (package) version src;
  nativeBuildInputs = [ python ];
  dontConfigure = true;
  postPatch = pkgs.lib.optionalString (package.pname == "requests") ''
    substituteInPlace docs/community/updates.rst \
      --replace-fail '.. include:: ../../HISTORY.md' $'.. include:: ../../HISTORY.md\n   :parser: myst_parser.sphinx_'
  '';
  buildPhase = ''
    runHook preBuild
    export DOC_SOURCE="$PWD/docs"
    sphinx-build -b html -c ${config} -w build-warnings.txt docs html
    if grep -q 'ERROR:' build-warnings.txt; then
      exit 1
    fi
    runHook postBuild
  '';
  installPhase = ''
    runHook preInstall
    mkdir -p "$out"
    cp -r html "$out/html"
    install -Dm644 LICENSE* "$out/LICENSE"
    runHook postInstall
  '';
}
