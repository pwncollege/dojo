{ pkgs }:

# burpsuite is packaged in a "buildFHSEnv" environment, which will not work in a container due to attempting to mount, but works fine without

let
  inherit (pkgs.burpsuite) pname version meta;

  description = "An integrated platform for performing security testing of web applications";

  # avoid burpsuite dumping ~500MB of data into the home directory
  extraFlags = "--disable-auto-update --data-dir=\\\${TMPDIR:-/tmp}/.BurpSuite";

in pkgs.stdenv.mkDerivation {
  inherit pname version meta description;

  src = pkgs.burpsuite;

  buildInputs = [ pkgs.makeWrapper ];

  installPhase = ''
      runHook preInstall

      initPath="$(sed -nE 's/.*--symlink ([^ ]*) \/init.*/\1/p' "$src/bin/burpsuite")"
      if [ -z "$initPath" ]; then
        echo "Error: Could not extract init script from burpsuite launcher" >&2
        exit 1
      fi

      mkdir -p "$out/bin"
      makeWrapper "$initPath" \
        "$out/bin/burpsuite" \
        --add-flags "${extraFlags}"

      cp -r "$src/share" "$out/share"

      runHook postInstall
  '';
}
