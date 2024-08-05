{ dosfstools, lib, mtools, runCommandLocal, stdenv }:

stdenv.mkDerivation {
  name = "setup-drive.img";

  src = lib.cleanSource ./setup-files;

  dontUnpack = true;
  dontConfigure = true;

  buildPhase = ''
    ${dosfstools}/bin/mkfs.fat -F 12 -C $out 1440
    cd $src
    ${mtools}/bin/mcopy -si $out ./Autounattend.xml ./setup.ps1 ./config_startup.ps1 ./sshd_config ::
  '';

  dontInstall = true;

  # save some time
  dontPatchELF = true;
  dontPatchShebangs = true;
}
