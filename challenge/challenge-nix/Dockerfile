FROM nixos/nix as nix

SHELL ["bash", "-ceov", "pipefail"]
COPY essientials.nix /essientials.nix

RUN nix-shell /essientials.nix
