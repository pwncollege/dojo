_final: prev:
let
  baselineBun = prev.bun.overrideAttrs (_oldAttrs: {
    src = prev.fetchurl {
      url = "https://github.com/oven-sh/bun/releases/download/bun-v${prev.bun.version}/bun-linux-x64-baseline.zip";
      hash = "sha256-nYokKSpwaAkCBdqsCloiP19pc29Sh+N7+I07QDHtx1A=";
    };
    sourceRoot = "bun-linux-x64-baseline";
  });
in
{
  opencode = (prev.opencode.override { bun = baselineBun; }).overrideAttrs (oldAttrs: {
    postPatch = (oldAttrs.postPatch or "") + ''
      substituteInPlace packages/opencode/script/build.ts \
        --replace-fail \
          '      if (item.avx2 === false) {' \
          '      if (item.avx2 !== false) {
        return !baselineFlag
      }
      if (item.avx2 === false) {'
      substituteInPlace packages/opencode/script/build.ts \
        --replace-fail \
          '        return baselineFlag' \
          '        return baselineFlag && item.abi === undefined'
    '';

    buildPhase = builtins.replaceStrings
      [ "bun --bun ./script/build.ts --single --skip-install" ]
      [ "bun --bun ./script/build.ts --single --baseline --skip-install" ]
      oldAttrs.buildPhase;
  });
}
