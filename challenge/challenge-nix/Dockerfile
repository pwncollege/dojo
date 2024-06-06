FROM nixos/nix as nix

SHELL ["bash", "-ceov", "pipefail"]
RUN nix-channel --update

COPY essientials.nix /essientials.nix
RUN nix-shell /essientials.nix
