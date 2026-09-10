{
  nixpkgs-pr-angr,
  pwndbg,
  system,
}:

[
  (import ./angr.nix { inherit nixpkgs-pr-angr; })
  (import ./novnc)
  (import ./opencode.nix)
  (import ./sage.nix)
  (import ./pwndbg.nix { inherit pwndbg system; })
]
