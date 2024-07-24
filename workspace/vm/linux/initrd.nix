{ pkgs, ssh }:
# { virtiofsd, qemu, openssh, start-stop-daemon, coreutils }:
with pkgs;

stdenv.mkDerivation {
  name = "initrd";
  version = 0.1;

  src = ./init;
  dontUnpack = true;

  # Modify UsePrivilegeSeparation no

  installPhase = ''
    mkdir -p $out/bin
    substitute $src $out/bin/init \
      --subst-var-by python "${pkgs.python3}/bin/python3" \
      --subst-var-by sshd_config "${ssh}/etc/ssh/sshd_config"
    chmod +x $out/bin/init
  '';
}