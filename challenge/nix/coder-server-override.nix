# This snippet shows how to override a nix package by copying all of the
# files of an already-built package, and then modifying some of them,
# thus avoiding a full rebuild.
#
# Example usage:
#
# Build the package:
#     nix-build --no-out-link change-file-after-build-example.nix
# See our replacement worked:
#     $ $(nix-build --no-out-link change-file-after-build-example.nix)/share/git/contrib/fast-import/git-import.sh
#     USAGE: git-import branch import-message
{
  pkgs ? import <nixpkgs> {},
  lib ? pkgs.lib,
}:
let
  originalPackage = pkgs.code-server;

  # We use `overrideAttrs` instead of defining a new `mkDerivation` to keep
  # the original package's `output`, `passthru`, and so on.
  coderServerRgFix = originalPackage.overrideAttrs (old: {
    name = "code-server-ripgrep-fix";

    # Using `buildCommand` replaces the original packages build phases.
    buildCommand = ''
      set -euo pipefail

      ${
        # Copy original files, for each split-output (`out`, `dev` etc.).
        # E.g. `${package.dev}` to `$dev`, and so on. If none, just "out".
        # Symlink all files from the original package to here (`cp -rs`),
        # to save disk space.
        # We could alternatiively also copy (`cp -a --no-preserve=mode`).
        lib.concatStringsSep "\n"
          (map
            (outputName:
              ''
                echo "Copying output ${outputName}"
                set -x
                cp -rs --no-preserve=mode "${originalPackage.${outputName}}" "''$${outputName}"
                set +x
              ''
            )
            (old.outputs or ["out"])
          )
      }

    mv "$out"/libexec/code-server/lib/vscode/node_modules/@vscode/ripgrep/bin/rg "$out"/libexec/code-server/lib/vscode/node_modules/@vscode/ripgrep/bin/rg.orig
    echo "$out"/libexec/code-server/lib/vscode/node_modules/@vscode/ripgrep/bin/rg
    cat <<'EOF' > "$out"/libexec/code-server/lib/vscode/node_modules/@vscode/ripgrep/bin/rg
#!/usr/bin/env python

import sys
import os

sys.argv[0] += ".orig"
if "--follow" in sys.argv:
    sys.argv.remove("--follow")
os.execv(sys.argv[0], sys.argv)
EOF
    chmod +x "$out"/libexec/code-server/lib/vscode/node_modules/@vscode/ripgrep/bin/rg
    '';

  });
in
  coderServerRgFix