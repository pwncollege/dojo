with import <nixpkgs> { };
# { virtiofsd, qemu, openssh }:

stdenv.mkDerivation {
  name = "windows-script";
  version = 0.1;

  src = ./windows;
  dontUnpack = true;

  # leave /opt/pwn.college shebangs intact
  dontPatchShebangs = true;

  installPhase = ''
    mkdir -p $out/bin
    substitute $src $out/bin/windows \
      --subst-var-by virtiofsd "${virtiofsd}" \
      --subst-var-by qemu "${qemu}" \
      --subst-var-by openssh "${openssh}"
    chmod +x $out/bin/windows
  '';
}
