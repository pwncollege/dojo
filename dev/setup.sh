#!/bin/sh

REPO_URL="https://github.com/pwncollege/dojo.git"
BRANCH="$1"

error () {
    echo "Error: $1" >&2
    exit 1
}

command -v docker >/dev/null 2>&1 || error "Docker is not installed. Please install Docker first."
docker info >/dev/null 2>&1 || error "Docker is not running. Please start Docker first."

WORKING_DIR=$(mktemp -d /tmp/dojo-XXXXXXXXXX) && [ -d "$WORKING_DIR" ] || error "Failed to create working directory."
WORKING_ID="${WORKING_DIR##*/dojo-}"
echo "[+] Working directory created at '$WORKING_DIR'; this will NOT be removed automatically and may consume significant disk space." >&2
cd "$WORKING_DIR"

echo "[-] Cloning dojo repository into '$WORKING_DIR/dojo'" >&2
git clone --depth=1 https://github.com/pwncollege/dojo.git || error "Failed to clone dojo repository."
echo "[+] Repository cloned successfully." >&2

case "$BRANCH" in
    ('')
        echo "[-] No branch specified, using 'main' branch." >&2
        ;;
    (*[!0-9]*)
        echo "[-] Checking out branch '$BRANCH'" >&2
        git -C dojo fetch origin "$BRANCH" || error "Failed to fetch branch '$BRANCH'."
        git -C dojo checkout "$BRANCH" || error "Failed to checkout branch '$BRANCH'."
        echo "[+] Checked out branch '$BRANCH'" >&2
        ;;
    (*)
        echo "[-] Checking out pull request #$BRANCH" >&2
        git -C dojo fetch origin "pull/$BRANCH/head:pull/$BRANCH" || error "Failed to fetch pull request."
        git -C dojo checkout "pull/$BRANCH" || error "Failed to checkout pull request."
        echo "[+] Checked out pull request #$BRANCH" >&2
        ;;
esac

echo "[-] Building Docker image with tag 'pwncollege/dojo:$WORKING_ID'" >&2
docker build -t "pwncollege/dojo:$WORKING_ID" dojo >/dev/null || error "Failed to build Docker image."
echo "[+] Docker image built successfully" >&2

echo "[-] Running Docker container with name 'dojo-$WORKING_ID'" >&2
docker run \
    --name "dojo-$WORKING_ID" \
    --privileged \
    -d "pwncollege/dojo:$WORKING_ID" >/dev/null 2>&1 || error "Failed to run Docker container."
echo "[+] Docker container is running" >&2

echo "[-] Installing VSCode server" >&2
docker exec "dojo-$WORKING_ID" sh -c 'curl -L "https://code.visualstudio.com/sha/download?build=stable&os=cli-alpine-x64" | tar -xz -C /usr/local/bin'
echo "[+] VSCode server installed successfully" >&2

echo "[-] Authenticating with VSCode server" >&2
while true; do
    docker exec -it "dojo-$WORKING_ID" sh -c 'code tunnel user login'
    docker exec "dojo-$WORKING_ID" sh -c 'code tunnel user show' >/dev/null || {
        echo "[-] Authentication failed, retrying..." >&2
        continue
    }
    echo "[+] Authentication successful" >&2
    break
done

docker exec -i "dojo-$WORKING_ID" sh -c 'cat > /etc/systemd/system/vscode-tunnel.service' <<EOF
[Unit]
Description=VS Code Remote Tunnel
After=network.target
[Service]
ExecStart=/usr/local/bin/code tunnel \
           --name dojo-$WORKING_ID \
           --accept-server-license-terms
Restart=on-failure
[Install]
WantedBy=multi-user.target
EOF
docker exec "dojo-$WORKING_ID" systemctl enable --now vscode-tunnel 2>/dev/null || error "Failed to enable VSCode tunnel service."
docker exec "dojo-$WORKING_ID" service vscode-tunnel status | while IFS= read -r line; do
    if echo "$line" | grep -q "Open this link in your browser https://vscode.dev/tunnel/dojo-$WORKING_ID"; then
        break
    fi
done
echo "[+] VSCode tunnel service installed and started successfully" >&2

echo "[+] Setup complete"
echo "[-] Access your VSCode instance at: https://vscode.dev/tunnel/dojo-$WORKING_ID/opt/pwn.college"
echo "[-] Cleanup with 'docker rm -f dojo-$WORKING_ID && sudo rm -rf $WORKING_DIR'"
