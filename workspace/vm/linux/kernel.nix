{ pkgs, kernelPackage }:

let
  # Function that builds a kernel from the provided Linux source with the
  # given config.
  buildKernel = kernelPackage: pkgs.linuxKernel.manualConfig {
    inherit (pkgs) stdenv lib;

    src = kernelPackage.src;
    configfile = ./kernel.config;

    version = kernelPackage.version;
    modDirVersion = kernelPackage.version;

    # Property comes from `manualConfig.nix` in nixpkgs and allows the read
    # `configfile` from within the derivation.
    allowImportFromDerivation = true;
  };
in
buildKernel kernelPackage