{ pkgs }:

let
  collections = {
    html = "10pnfq0sf03qsgkdscrnrcqi1pbmcbw1dxp04xzn0rl59sxk95ni";
    css = "0pl6rkcqjcl4cas0qrlv75lvn431ypf5q1nmms17rc8w1gnk3di3";
    javascript = "0y60yfsg9f32fz2na9zp8kf3vzs2sv7imbj20hfhhma4nr9h1xc2";
    dom = "1hqmm6jwj01ldcw7mkps8dck18vhvx3g2m8kjqcfl38hzqiazcvr";
    http = "0y6bf4zw7qghh7vyw4db0n0ybni91n00i2p8hq57p3ghaqfs7wc3";
    "python~3.13" = "1ffncwcjwvf64li5j274lyk2iq2qancr8zp2b3m5gp84j8r5wiic";
    sqlite = "1z64abl8jb78k9b4hw19l6a4kn37pwz14pxqmljgdnsfanxjcip5";
    flask = "0hlc42nkmc78mi51s4h36x5x74l5x3rd3c69gfr3zk64gmcjs4fh";
    requests = "0z7ksaypjcj9wl3g6ab1i8q5n10rxvnd60ps572vsbcyli5qmrci";
  };
  revision = "29952fe571b3eef4be58152192d450dea352e7e4";
  fetchClient =
    path: sha256:
    pkgs.fetchurl {
      url = "https://raw.githubusercontent.com/dimitry-ishenko-cpp/devdocs/${revision}/${path}";
      inherit sha256;
    };
  devopen = fetchClient "bin/devopen.in" "1wmsa2m3vfdaj5vfidpmnchg51g6cy4yvqbdhsn7prdmcz1bj0y1";
  devgrep = fetchClient "bin/devgrep.in" "0p9fwmx9c75phibwnjr8hqhkdwgw99jirpfgkvahl9lfvqwl7s8m";
  config = fetchClient "elinks/elinks.conf" "0pmivy1kg4a872ssqjgw41f3949a0pdbjq1fy3smqq99ma4cwq5z";
  hooks = fetchClient "elinks/hooks.py" "1na1k615sd4ijq3d2fd37s8rgwwrwaw8zqyc155kfrfm0q44bvxl";
  license = fetchClient "LICENSE.md" "0mh4d01s2xdvspqcjfsgyr6p1nlnkxlxk01zzwc79pqnwskbslc9";
  python = pkgs.python3.withPackages (ps: [
    ps.lxml
    ps.pygments
  ]);
  elinks = pkgs.elinks.override {
    enablePython = true;
    inherit python;
  };
  viewer = pkgs.writeShellApplication {
    name = "devdocs-elinks";
    runtimeInputs = [ pkgs.coreutils ];
    text = ''
      devdocs_config=$(mktemp -d -t devdocs-elinks.XXXXXXXX)
      trap 'rm -rf -- "$devdocs_config"' EXIT
      cp ${config} "$devdocs_config/elinks.conf"
      cp ${hooks} "$devdocs_config/hooks.py"
      export PYTHONPATH="${python}/${python.sitePackages}"
      ${elinks}/bin/elinks -config-dir "$devdocs_config" -no-connect 1 \
        -eval "set terminal.''${TERM:-xterm-256color}.transparency = 0" \
        -eval 'set document.colors.background = "black"' "$@"
    '';
  };
  prepare = pkgs.writeText "devdocs-prepare.py" ''
    import json
    import posixpath
    from pathlib import Path
    import sys
    from urllib.parse import unquote, urljoin, urlsplit, urlunsplit

    from lxml import html

    source, destination = map(Path, sys.argv[1:])
    pages = json.loads((source / "db.json").read_text())

    def filename(path):
        return path if path.endswith(".html") else path + ".html"

    files = {filename(page) for page in pages}
    for page, content in pages.items():
        document = html.fragment_fromstring(content, create_parent="div")
        for link in document.xpath(".//a[@href]"):
            target = urlsplit(link.get("href"))
            if target.scheme or target.netloc or not target.path:
                continue
            resolved = unquote(
                urlsplit(urljoin("/" + filename(page), target.path)).path
            ).lstrip("/")
            candidate = filename(resolved)
            if candidate in files:
                relative = posixpath.relpath(
                    candidate, posixpath.dirname(filename(page)) or "."
                )
                link.set(
                    "href", urlunsplit(("", "", relative, target.query, target.fragment))
                )
        output = destination / filename(page)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(html.tostring(document, encoding="unicode"))

    index = {}
    for entry in json.loads((source / "index.json").read_text())["entries"]:
        path, separator, anchor = entry["path"].partition("#")
        target = filename(path)
        assert target in files, entry
        index[entry["name"]] = target + separator + anchor
    (destination / "index.json").write_text(json.dumps(index))
  '';
  docs =
    pkgs.runCommand "devdocs-terminal-data"
      {
        nativeBuildInputs = [ python ];
      }
      ''
        mkdir -p "$out/html"
        ${pkgs.lib.concatStringsSep "\n" (
          pkgs.lib.mapAttrsToList (
            slug: sha256:
            let
              archive = pkgs.fetchurl {
                name = "devdocs-${builtins.replaceStrings [ "~" ] [ "-" ] slug}.tar.gz";
                url = "https://downloads.devdocs.io/${slug}.tar.gz";
                inherit sha256;
              };
            in
            ''
              mkdir -p "${slug}"
              tar --warning=no-unknown-keyword --exclude='._*' -xf ${archive} -C "${slug}"
              python ${prepare} "${slug}" "$out/html/${slug}"
            ''
          ) collections
        )}
      '';
in
pkgs.runCommand "devdocs-terminal"
  {
    nativeBuildInputs = [ pkgs.makeWrapper ];
    meta.mainProgram = "devgrep";
    passthru = { inherit docs collections elinks; };
  }
  ''
    mkdir -p "$out/bin" "$out/share/devdocs-terminal"
    cp ${devopen} "$out/bin/devopen"
    cp ${devgrep} "$out/bin/devgrep"
    cp ${license} "$out/share/devdocs-terminal/LICENSE.md"
    substituteInPlace "$out/bin/devopen" "$out/bin/devgrep" \
      --replace-fail '@DEVDOCS_INSTALL_DATADIR@' '${docs}' \
      --replace-fail '@PROJECT_VERSION@' '${builtins.substring 0 8 revision}' \
      --replace-fail '#!/usr/bin/env python3' '#!${python}/bin/python3'
    substituteInPlace "$out/bin/devopen" \
      --replace-fail 'www = [ "elinks", "-config-dir", root_path / "elinks", "-no-connect", "1" ]' \
        'www = [ "${viewer}/bin/devdocs-elinks" ]'
    chmod +x "$out/bin/devopen" "$out/bin/devgrep"
    wrapProgram "$out/bin/devopen" --prefix PATH : ${pkgs.lib.makeBinPath [ pkgs.fzf ]}
    wrapProgram "$out/bin/devgrep" --prefix PATH : ${pkgs.lib.makeBinPath [ pkgs.fzf ]}
    ln -s devgrep "$out/bin/devdocs"
    ln -s ${docs}/html "$out/share/devdocs-terminal/html"
  ''
