_final: prev: {
  novnc = prev.novnc.overrideAttrs (oldAttrs: {
    version = "unstable-2026-09-07";
    src = prev.fetchFromGitHub {
      owner = "novnc";
      repo = "noVNC";
      rev = "acca57b997f206683d27796829ee1f72da37002a";
      hash = "sha256-MlnFM3DkBBuGIAXbJYjyb5qEDz8ayxN4E7lCZ3kT6Pw=";
    };
    patches = (oldAttrs.patches or []) ++ [
      ./novnc/clipboard.patch
      ./novnc/reconnect.patch
    ];
  });
}
