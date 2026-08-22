{ nixpkgs-pr-angr }:

# Evaluate only the PR's angr-family package recipes in the active nixpkgs
# package set, instead of importing the PR as a second general package set.
final: prev:
let
  angr-capstone = final.callPackage "${nixpkgs-pr-angr}/pkgs/by-name/ca/capstone/package.nix" { };
in
{
  angr-management =
    (final.callPackage "${nixpkgs-pr-angr}/pkgs/by-name/an/angr-management/package.nix" { })
    .overridePythonAttrs
      (old: {
        dependencies = old.dependencies ++ final.python312Packages.angr.optional-dependencies.unicorn;
      });
  pythonPackagesExtensions = prev.pythonPackagesExtensions ++ [
    (
      python-final: python-prev:
      let
        fromAngrPr =
          name: args:
          python-final.callPackage "${nixpkgs-pr-angr}/pkgs/development/python-modules/${name}" args;
      in
      {
        angr = fromAngrPr "angr" { };
        angr-data = fromAngrPr "angr-data" { };
        archinfo = fromAngrPr "archinfo" { };
        binsync = fromAngrPr "binsync" { };
        capstone = fromAngrPr "capstone" {
          capstone = angr-capstone;
        };
        claripy = fromAngrPr "claripy" { };
        cle = fromAngrPr "cle" {
          uefi-firmware = python-final.uefi-firmware-parser;
        };
        declib = fromAngrPr "declib" { };
        pypcode = fromAngrPr "pypcode" { };
        pydemumble = fromAngrPr "pydemumble" { };
        pyside6-qtads = fromAngrPr "pyside6-qtads" { };
        pyqodeng = fromAngrPr "pyqodeng" { };
        pyvex = fromAngrPr "pyvex" { };
        pyxdia = fromAngrPr "pyxdia" { };
      }
      // final.lib.optionalAttrs (python-prev.python.pythonVersion == "3.12") {
        lmdb = python-prev.lmdb.overridePythonAttrs (old: {
          # This page-fault-count assertion is kernel/cache dependent.
          disabledTests = (old.disabledTests or [ ]) ++ [ "test_preload" ];
        });
      }
    )
  ];
}
