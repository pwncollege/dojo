{
  nixpkgs-pr-angr,
  pwndbg,
  system,
}:

[
  (import ./angr.nix { inherit nixpkgs-pr-angr; })
  (import ./sage.nix)
  (import ./pwndbg.nix { inherit pwndbg system; })
]
