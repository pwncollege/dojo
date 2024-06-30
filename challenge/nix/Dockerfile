FROM nixos/nix as full

SHELL ["bash", "-ceov", "pipefail"]
RUN nix-channel --update

RUN mkdir -p /nix/bin

COPY essientials.nix /build/essientials.nix
RUN nix-shell /build/essientials.nix

# Build Code Server
COPY code-server-build.nix /build/code-server-build.nix
COPY coder-server-override.nix /build/coder-server-override.nix

RUN nix-shell /build/code-server-build.nix

# Build Desktop

COPY build-desktop.nix /build/build-desktop.nix
RUN nix-shell /build/build-desktop.nix

# Copy to out

CMD cp -r /nix/* /out/