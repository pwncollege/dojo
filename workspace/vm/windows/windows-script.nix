{ pkgs }:

let
  dojo-service = import ../../services/service.nix { inherit pkgs; };
  windows-vm = pkgs.callPackage ./windows-vm.nix { };
  virtio-win-drivers = pkgs.callPackage ./virtio-win-drivers.nix { };
  setup-drive = pkgs.callPackage ./setup-drive.nix { };
  server-iso = pkgs.callPackage ./server-iso.nix { };
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
      --subst-var-by windows-vm "${windows-vm}" \
      --subst-var-by virtio-win-drivers "${virtio-win-drivers}" \
      --subst-var-by setup-drive "${setup-drive}" \
      --subst-var-by server-iso "${server-iso}"
    chmod +x $out/bin/windows
    runHook postInstall
  '';
}
