FROM nixos/nix as full

SHELL ["bash", "-ceov", "pipefail"]
RUN nix-channel --update

COPY essientials.nix /essientials.nix
RUN nix-shell /essientials.nix

# Build Code Server
RUN nix-env -iA nixpkgs.code-server nixpkgs.python312

RUN <<EOF
    mkdir -p /opt/code-server/extensions
    wget -O /tmp/ms-vscode-cpptools.vsix 'https://github.com/microsoft/vscode-cpptools/releases/download/v1.20.5/cpptools-linux.vsix'
    code-server --extensions-dir=/opt/code-server/extensions \
        --install-extension ms-python.python \
        --install-extension /tmp/ms-vscode-cpptools.vsix
    chmod +x /opt/code-server/extensions/ms-vscode.cpptools-*/{bin/cpptools*,bin/libc.so,debugAdapters/bin/OpenDebugAD7,LLVM/bin/clang-*}
    rm -rf /root/.cache/code-server /root/.local/share/code-server /tmp/ms-vscode-cpptools.vsix
EOF