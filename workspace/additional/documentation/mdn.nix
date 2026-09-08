{ pkgs }:

let
  archives = {
    CSS = "sha256-E7Jz+ISATlA0s3am/Ab9emEwjQ6TQtSRJ6dBrpOs3AA=";
    HTML = "sha256-W2fi1GarQjg2AkO5ya8Vme8/XzN0W3uyzgC50i+tBh4=";
    HTTP = "sha256-lux/4xe2ugF+6DVx7vuyiu8pPSSZWBhn4hZiBMm8DKw=";
    JavaScript = "sha256-S/8ImKgBWqi32pNc8hgzkuHOfPDquxKtMUGXemet77s=";
    SVG = "sha256-1GU08EC3w6f1riwTemN7C3jY3WO/jq5cCQbpEuxQvVk=";
  };
  index = pkgs.writeText "mdn-index.html" ''
    <!doctype html><html lang="en"><head><meta charset="utf-8"><title>MDN offline documentation</title></head><body>
    <h1>MDN offline documentation</h1><ul>
    ${pkgs.lib.concatMapStringsSep "\n" (name: ''
      <li><a href="developer.mozilla.org/en-US/docs/Web/${
        if name == "JavaScript" then "JavaScript/Reference" else name
      }.html">${name}</a></li>
    '') (builtins.attrNames archives)}
    <li><a href="developer.mozilla.org/en-US/docs/Web/API.html">Web APIs / DOM</a></li>
    </ul><p>MDN reference collections packaged by <a href="https://kapeli.com/mdn_offline">Kapeli</a>, not a complete MDN mirror.
    Original attribution and contributor files are retained. Local links and offline presentation have been adapted.</p>
    </body></html>
  '';
in
pkgs.runCommand "mdn-offline-docs" { passthru.version = "2026-07-17"; } ''
  mkdir -p "$out/html"
  ${pkgs.lib.concatStringsSep "\n" (
    pkgs.lib.mapAttrsToList (name: hash: ''
      tar -xzf ${
        pkgs.fetchurl {
          url = "https://kapeli.com/feeds/zzz/mdn/${name}.tgz";
          inherit hash;
        }
      } --strip-components=1 --no-same-owner -C "$out/html"
    '') archives
  )}
  cp ${index} "$out/html/index.html"
''
