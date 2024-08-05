{ pkgs }:

let
  dojo-service = import ../../services/service.nix { inherit pkgs; };
in
pkgs.stdenv.mkDerivation {
  pname = "windows-script";
  version = "0.1.0";

  src = ./windows;
  dontUnpack = true;

  # leave /opt/pwn.college shebangs intact
  dontPatchShebangs = true;

  installPhase = ''
    mkdir -p $out/bin
    substitute $src $out/bin/windows \
      --subst-var-by virtiofsd "${pkgs.virtiofsd}" \
      --subst-var-by qemu "${pkgs.qemu}" \
      --subst-var-by openssh "${pkgs.openssh}" \
      --subst-var-by coreutils "${pkgs.coreutils}" \
      --subst-var-by dojo-service "${dojo-service}"
    chmod +x $out/bin/windows
  '';
}
