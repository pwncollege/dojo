{ pkgs, service, kernel, initrd }:
# { virtiofsd, qemu, openssh, start-stop-daemon, coreutils }:
with pkgs;

stdenv.mkDerivation {
  name = "linux-script";
  version = 0.1;

  src = ./vm;
  dontUnpack = true;


   # --subst-var-by start-stop-daemon "${start-stop-daemon}" \

  installPhase = ''
    mkdir -p $out/bin
    echo a
    substitute $src $out/bin/vm \
      --subst-var-by virtiofsd "${virtiofsd}" \
      --subst-var-by qemu "${qemu}" \
      --subst-var-by openssh "${openssh}" \
      --subst-var-by tail "${coreutils}" \
      --subst-var-by service "${service}" \
      --subst-var-by kernel "${kernel}" \
      --subst-var-by gdb "${gdb}" \
      --subst-var-by python "${python3}/bin/python3" \
      --subst-var-by initrd "${initrd}/bin/init"
      chmod +x $out/bin/vm
  '';
}