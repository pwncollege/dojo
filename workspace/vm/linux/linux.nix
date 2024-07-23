{ pkgs, service }:

let
  kernelPackage = pkgs.linuxKernel.kernels.linux_5_4;
  kernel = pkgs.callPackage ./kernel.nix { inherit pkgs kernelPackage; };
  initrd = pkgs.callPackage ./initrd.nix { inherit pkgs; };
  linux-script = pkgs.callPackage ./linux-script.nix { inherit pkgs service kernel initrd; };
in
{ 
  packages = [
    linux-script
    kernel
    initrd
  ];
}