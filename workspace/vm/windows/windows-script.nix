{ virtiofsd, qemu, openssh, stdenv }:

stdenv.mkDerivation {
  pname = "windows-script";
  version = "0.1.0";

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
