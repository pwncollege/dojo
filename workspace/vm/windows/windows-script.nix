{ pkgs }:

let
  dojo-service = import ../../services/service.nix { inherit pkgs; };
  windows-vm = pkgs.callPackage ./windows-vm.nix { };
in
pkgs.stdenv.mkDerivation {
  pname = "windows-script";
  version = "0.1.0";

  src = ./windows;
  dontUnpack = true;

  # leave /opt/pwn.college shebangs intact
  dontPatchShebangs = true;

  installPhase = ''
    runHook preInstall
    mkdir -p $out/bin
    substitute $src $out/bin/windows \
      --subst-var-by virtiofsd "${pkgs.virtiofsd}" \
      --subst-var-by qemu "${pkgs.qemu}" \
      --subst-var-by openssh "${pkgs.openssh}" \
      --subst-var-by coreutils "${pkgs.coreutils}" \
      --subst-var-by dojo-service "${dojo-service}" \
      --subst-var-by windows-vm ${windows-vm}
    chmod +x $out/bin/windows
    runHook postInstall
  '';
}
