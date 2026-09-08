{ pkgs }:

let
  revision = "bf7c500b8129e076e5beda8d9932a7db879a6841";
  content = pkgs.fetchFromGitHub {
    owner = "mdn";
    repo = "content";
    rev = revision;
    hash = "sha256-3QH9OGUK4PeZnKsY7qgKelJ6pfbKnEgAsRysJRkPM8g=";
  };
  rari = import ./rari.nix { inherit pkgs; };
  dependencies = builtins.fromJSON (builtins.readFile ./mdn-dependencies.json);
  extensionExamples = pkgs.fetchurl {
    url = "https://raw.githubusercontent.com/mdn/webextensions-examples/5ab9204e76a723d3c92b0f44c4e430011799c6a0/examples.json";
    hash = "sha256-EaOzMBw5MKJOMN2Wv+fr6lTnmXsi9k5k4QoRSd1XJ0o=";
  };
in
pkgs.runCommand "mdn-doc-${builtins.substring 0 12 revision}"
  {
    nativeBuildInputs = [
      rari
      pkgs.python3
    ];
    passthru = { inherit revision content; };
  }
  ''
    export DEPS_DATA_DIR="$TMPDIR/deps"
    ${pkgs.lib.concatMapStringsSep "\n" (dependency: ''
      mkdir -p "$DEPS_DATA_DIR/rari/${dependency.name}"
      tar -xzf ${pkgs.fetchurl { inherit (dependency) url hash; }} \
        -C "$DEPS_DATA_DIR/rari/${dependency.name}"
    '') dependencies}
    install -Dm644 ${extensionExamples} "$DEPS_DATA_DIR/rari/web_ext_examples/data.json"
    install -Dm644 ${pkgs.writeText "empty-developer-signals.json" "{}"} \
      "$DEPS_DATA_DIR/rari/developer_signals/data.json"
    export CONTENT_ROOT=${content}/files
    export BUILD_OUT_ROOT="$TMPDIR/rendered"
    export RAYON_NUM_THREADS="$NIX_BUILD_CORES"
    mkdir -p "$out"
    rari build --no-basic --content --locale en-US --issues "$out/issues.json"
    python ${./render-mdn.py} "$BUILD_OUT_ROOT" ${content} \
      "$DEPS_DATA_DIR/rari/@mdn/browser-compat-data/package/data.json" "$out"
  ''
