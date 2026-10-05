{ pkgs }:

let
  collections = {
    html = "10pnfq0sf03qsgkdscrnrcqi1pbmcbw1dxp04xzn0rl59sxk95ni";
    css = "05g4skfzd9i0shzm5zpibv4n66n6vvr7b3bxp22wq1r1lyvmcm29";
    javascript = "1a1xqxyssc2h22c3cl5kzbzr51p4fpzk8qjqsg02aqax8d3grqgy";
    dom = "0vvcyk2483xp08wqs1y9bhm9caj007yp52ypli0mv0g0m3x0xmrf";
    http = "0y6bf4zw7qghh7vyw4db0n0ybni91n00i2p8hq57p3ghaqfs7wc3";
    "python~3.13" = "1ffncwcjwvf64li5j274lyk2iq2qancr8zp2b3m5gp84j8r5wiic";
    sqlite = "1z64abl8jb78k9b4hw19l6a4kn37pwz14pxqmljgdnsfanxjcip5";
    flask = "0hlc42nkmc78mi51s4h36x5x74l5x3rd3c69gfr3zk64gmcjs4fh";
    requests = "0z7ksaypjcj9wl3g6ab1i8q5n10rxvnd60ps572vsbcyli5qmrci";
  };
  revision = "29952fe571b3eef4be58152192d450dea352e7e4";
  src = pkgs.fetchgit {
    url = "https://github.com/dimitry-ishenko-cpp/devdocs.git";
    rev = revision;
    sparseCheckout = [
      "bin"
      "elinks"
    ];
    hash = "sha256-0w29inZ5CMGex3DxIAUWErM30yMgM1Dqw1QWmRzDssA=";
  };
  x86Reference =
    pkgs.runCommand "felix-cloutier-x86-reference"
      {
        nativeBuildInputs = [ pkgs.wget ];
        outputHashMode = "recursive";
        outputHashAlgo = "sha256";
        outputHash = "sha256-wKzeAAfdaWefx48u/WYJbvHXuhDQKp9CrsrKKZIKL6s=";
      }
      ''
        wget --recursive --level=1 --no-parent --no-host-directories \
          --cut-dirs=1 --adjust-extension --convert-links --page-requisites \
          --ca-certificate=${pkgs.cacert}/etc/ssl/certs/ca-bundle.crt \
          --tries=3 --timeout=30 --no-verbose --directory-prefix="$out" \
          https://www.felixcloutier.com/x86/
      '';
  syscallTable = pkgs.fetchurl {
    name = "x64-syscall-table.html";
    url = "https://x64.syscall.sh/";
    hash = "sha256-ffznzAVr67RTDad9Iwe6zyN5wXt/GCXDrVhxlnsNoB4=";
  };
  abiReference = pkgs.fetchurl {
    name = "system-v-abi.html";
    url = "https://osdev.wiki/wiki/System_V_ABI?oldid=29518&action=render";
    hash = "sha256-KlixiSpCJOmyhEC8wzseUqLio9fBWwSLrhNg74YwWcA=";
  };
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
      cp ${src}/elinks/{elinks.conf,hooks.py} "$devdocs_config/"
      export PYTHONPATH="${python}/${python.sitePackages}"
      ${elinks}/bin/elinks -config-dir "$devdocs_config" -no-connect 1 \
        -eval "set terminal.''${TERM:-xterm-256color}.transparency = 0" \
        -eval 'set document.colors.background = "black"' "$@"
    '';
  };
  docs =
    pkgs.runCommand "devdocs-terminal-data"
      {
        nativeBuildInputs = [ python ];
      }
      ''
        mkdir -p "$out/html"
        ${pkgs.lib.concatMapAttrsStringSep "\n" (
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
            python ${./prepare.py} "${slug}" "$out/html/${slug}"
          ''
        ) collections}
        python ${./references.py} \
          ${x86Reference} \
          ${syscallTable} ${abiReference} "$out/html"
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
    cp ${src}/LICENSE.md "$out/share/devdocs-terminal/LICENSE.md"
    install -m755 ${src}/bin/devopen.in "$out/bin/devopen"
    install -m755 ${src}/bin/devgrep.in "$out/bin/devgrep"
    substituteInPlace "$out/bin/devopen" "$out/bin/devgrep" \
      --replace-fail '@DEVDOCS_INSTALL_DATADIR@' '${docs}' \
      --replace-fail '@PROJECT_VERSION@' '${builtins.substring 0 8 revision}' \
      --replace-fail '#!/usr/bin/env python3' '#!${python}/bin/python3'
    substituteInPlace "$out/bin/devopen" \
      --replace-fail 'www = [ "elinks", "-config-dir", root_path / "elinks", "-no-connect", "1" ]' \
        'www = [ "${viewer}/bin/devdocs-elinks" ]'
    wrapProgram "$out/bin/devopen" --prefix PATH : ${pkgs.lib.makeBinPath [ pkgs.fzf ]}
    wrapProgram "$out/bin/devgrep" --prefix PATH : ${pkgs.lib.makeBinPath [ pkgs.fzf ]}
    ln -s devgrep "$out/bin/devdocs"
    ln -s ${docs}/html "$out/share/devdocs-terminal/html"
  ''
